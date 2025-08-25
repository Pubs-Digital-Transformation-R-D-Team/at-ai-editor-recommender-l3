import boto3
import os
import asyncio

DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
DEFAULT_SYSTEM = [{ "text": "You are a helpful assistant" }]

def llm_call_lc(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.3, "topK": 20}

    model_response = client.invoke(text, inf_params)

    return model_response.content

def llm_call(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 2048, "topP": 0.1, "temperature": 0.3}

    additionalModelRequestFields = {
        "inferenceConfig": {
            "topK": 20
        }
    }

    messages = [
        {"role": "user", "content": [{"text": text}]},
    ]
    
    model_response = client.converse(
        modelId=modelId, 
        messages=messages, 
        # system=system, 
        inferenceConfig=inf_params,
        additionalModelRequestFields=additionalModelRequestFields
    )

    return model_response["output"]["message"]["content"][0]["text"]

async def async_llm_call(*args, **kwargs):
    return await asyncio.to_thread(llm_call, *args, **kwargs)

def load_mock_editor(id):
    """
    Loads the mock editor file with the given id from mock_editors directory.
    Raises FileNotFoundError if the file does not exist.
    """
    filename = os.path.join("mock_editors", f"{id}.md")
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"Mock editor file not found: {filename}")
    with open(filename, "r") as f:
        return f.read()


