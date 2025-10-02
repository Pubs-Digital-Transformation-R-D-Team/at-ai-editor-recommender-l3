import os
import asyncio
from typing import List, Dict, Any



DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
DEFAULT_SYSTEM = [{ "text": "You are an expert Chemistry Editor"}]


def llm_call_lc(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0, "topK": 20}

    model_response = client.invoke(text, inf_params)

    return model_response.content

def llm_call(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0}

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


# async def async_llm_call(*args, **kwargs):
#     return await asyncio.to_thread(llm_call, *args, **kwargs)


async def async_llm_call(client, text: str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0}
    
    additionalModelRequestFields = {
        "inferenceConfig": {
            "topK": 20
        }
    }

    messages = [
        {"role": "user", "content": [{"text": text}]},
    ]
    
    # If client is async aioboto3 client
    async with client as bedrock_client:
        model_response = await bedrock_client.converse(
            modelId=modelId, 
            messages=messages, 
            inferenceConfig=inf_params,
            additionalModelRequestFields=additionalModelRequestFields
        )

    return model_response["output"]["message"]["content"][0]["text"]


def load_file(filename):
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"File not found: {filename}")
    with open(filename, "r") as f:
        return f.read()