#!/usr/bin/env python3
"""
Standalone script to test IRSA (IAM Roles for Service Accounts) functionality
Run this directly in your pod to verify AWS credentials and Bedrock access.
"""

import boto3
import os
import json
from botocore.exceptions import ClientError, NoCredentialsError
import sys

def print_section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")

def check_environment_variables():
    """Check AWS-related environment variables"""
    print_section("Environment Variables")
    
    aws_vars = [
        'AWS_REGION',
        'AWS_DEFAULT_REGION', 
        'AWS_ROLE_ARN',
        'AWS_WEB_IDENTITY_TOKEN_FILE'
    ]
    
    for var in aws_vars:
        value = os.environ.get(var)
        if value:
            if var == 'AWS_WEB_IDENTITY_TOKEN_FILE':
                # Check if token file exists
                exists = os.path.exists(value) if value else False
                print(f"✓ {var}: {value} (exists: {exists})")
            else:
                print(f"✓ {var}: {value}")
        else:
            print(f"✗ {var}: Not set")

def check_token_file():
    """Check the web identity token file"""
    print_section("Web Identity Token File")
    
    token_file = os.environ.get('AWS_WEB_IDENTITY_TOKEN_FILE')
    if not token_file:
        print("✗ AWS_WEB_IDENTITY_TOKEN_FILE not set")
        return
        
    try:
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token = f.read().strip()
            print(f"✓ Token file exists: {token_file}")
            print(f"✓ Token length: {len(token)} characters")
            print(f"✓ Token preview: {token[:50]}...")
        else:
            print(f"✗ Token file does not exist: {token_file}")
    except Exception as e:
        print(f"✗ Error reading token file: {e}")

def test_sts_credentials():
    """Test STS assume role functionality"""
    print_section("STS Credentials Test")
    
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        
        if credentials:
            print("✓ Credentials found!")
            print(f"  Access Key ID: {credentials.access_key[:10]}...")
            print(f"  Secret Access Key: {'*' * 20}")
            print(f"  Session Token: {'Present' if credentials.token else 'Not Present'}")
            
            # Test STS get-caller-identity
            sts_client = session.client('sts')
            identity = sts_client.get_caller_identity()
            print(f"✓ Caller Identity:")
            print(f"  Account: {identity.get('Account')}")
            print(f"  UserId: {identity.get('UserId')}")
            print(f"  Arn: {identity.get('Arn')}")
            
        else:
            print("✗ No credentials found")
            return False
            
    except NoCredentialsError:
        print("✗ No credentials available")
        return False
    except Exception as e:
        print(f"✗ Error getting credentials: {e}")
        return False
        
    return True

def test_bedrock_access():
    """Test Bedrock access"""
    print_section("Bedrock Access Test")
    
    try:
        # Test in us-east-1 (where your deployment is configured)
        client = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        # Try to list foundation models
        print("Testing list_foundation_models...")
        bedrock_client = boto3.client('bedrock', region_name='us-east-1')
        models = bedrock_client.list_foundation_models()
        print(f"✓ Successfully listed {len(models.get('modelSummaries', []))} foundation models")
        
        # Test with your specific model
        model_id = 'us.amazon.nova-premier-v1:0'
        print(f"\nTesting converse API with model: {model_id}")
        
        messages = [
            {"role": "user", "content": [{"text": "Hello, this is a test message."}]},
        ]
        
        response = client.converse(
            modelId=model_id,
            messages=messages,
            inferenceConfig={
                "maxTokens": 100,
                "temperature": 0.0
            }
        )
        
        response_text = response["output"]["message"]["content"][0]["text"]
        print(f"✓ Bedrock converse API test successful!")
        print(f"  Response: {response_text[:100]}...")
        
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"✗ Bedrock ClientError: {error_code} - {error_message}")
        
        if error_code == 'UnauthorizedOperation':
            print("  This suggests the IAM role doesn't have the required Bedrock permissions")
        elif error_code == 'IncompleteSignatureException':
            print("  This suggests there's an issue with AWS credential signing")
            
        return False
    except Exception as e:
        print(f"✗ Bedrock error: {e}")
        return False

def test_specific_bedrock_permissions():
    """Test specific Bedrock permissions from your policy"""
    print_section("Bedrock Permissions Test")
    
    permissions_to_test = [
        ('bedrock', 'list_foundation_models'),
        ('bedrock-runtime', 'converse')
    ]
    
    for service, operation in permissions_to_test:
        try:
            if service == 'bedrock' and operation == 'list_foundation_models':
                client = boto3.client('bedrock', region_name='us-east-1')
                result = client.list_foundation_models()
                print(f"✓ {service}:{operation} - Success")
                
            elif service == 'bedrock-runtime' and operation == 'converse':
                client = boto3.client('bedrock-runtime', region_name='us-east-1')
                # Simple test call
                messages = [{"role": "user", "content": [{"text": "test"}]}]
                result = client.converse(
                    modelId='us.amazon.nova-premier-v1:0',
                    messages=messages,
                    inferenceConfig={"maxTokens": 10}
                )
                print(f"✓ {service}:{operation} - Success")
                
        except Exception as e:
            print(f"✗ {service}:{operation} - Failed: {e}")

def main():
    print("IRSA and AWS Bedrock Testing Script")
    print("=" * 60)
    
    # Run all tests
    env_ok = True
    check_environment_variables()
    check_token_file()
    
    creds_ok = test_sts_credentials()
    if not creds_ok:
        print("\n⚠️  Credential test failed. Bedrock tests will likely fail.")
    
    bedrock_ok = test_bedrock_access()
    test_specific_bedrock_permissions()
    
    # Summary
    print_section("Summary")
    if creds_ok and bedrock_ok:
        print("✅ All tests passed! IRSA is working correctly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Check the output above for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()