import os
import aioboto3
import json


DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
DEFAULT_SYSTEM = [{ "text": "You are an expert Chemistry Editor"}]


def llm_call_lc(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0, "topK": 20}

    model_response = client.invoke(text, inf_params)

    return model_response.content

def llm_call(client, text:str, modelId=DEFAULT_MODEL_ID, system=DEFAULT_SYSTEM):
    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0}

    # additionalModelRequestFields = {
    #     "inferenceConfig": {
    #         "topK": 20
    #     }
    # }

    messages = [
        {"role": "user", "content": [{"text": text}]},
    ]
    
    model_response = client.converse(
        modelId=modelId, 
        messages=messages, 
        # system=system, 
        inferenceConfig=inf_params
        # additionalModelRequestFields=additionalModelRequestFields
    )

    return model_response["output"]["message"]["content"][0]["text"]


# async def async_llm_call(*args, **kwargs):
#     return await asyncio.to_thread(llm_call, *args, **kwargs)


async def anthropic_llm_call(client, text:str, modelId: str = DEFAULT_MODEL_ID):
    print("starting anthropic_llm_call")
    if os.getenv("MOCK_LLM_RESPONSE", "false").lower() == "true":
        print("Returning mock LLM response")
        mock_response = {
            "selectedEditorOrcId": "1234",
            "selectedEditorPersonId": "1234",
            "reasoning": "Mock LLM is enabled, so this is a mock response.",
            "runnerUp": "No Runner up - mock response",
            "filteredOutEditors": "None filtered for COI - mock response"
        }
        return json.dumps(mock_response)

    message = await client.messages.create(
        model=modelId,
        system="You are a JSON-only response system. You must always respond with valid, properly formatted JSON. Never include explanations, comments, or any text outside the JSON structure. Do not use markdown code blocks. Return only the raw JSON object.",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": text
                    }
                ]
            }
        ],
        max_tokens=4096,
        top_p=0.1,
        temperature=0.0
    )
    print("finished anthropic_llm_call")
    return message.content[0].text

    

async def async_llm_call(
    text: str,
    *,
    modelId: str = DEFAULT_MODEL_ID,
    region_name: str = "us-east-1",
    session: aioboto3.Session | None = None,
) -> str:
    """Native async Bedrock converse call reused with a shared aioboto3.Session.

    Because `Converse` is not covered by the Bedrock auto-instrumentation we
    start an OpenInference span manually so that traces once again contain the
    LLM call.
    """

    inf_params = {"maxTokens": 4096, "topP": 0.1, "temperature": 0.0}
    additionalModelRequestFields = {"inferenceConfig": {"topK": 20}}
    messages = [{"role": "user", "content": [{"text": text}]}]

    sess = session or aioboto3.Session()
    async with sess.client("bedrock-runtime", region_name=region_name) as br:
        resp = await br.converse(
            modelId=modelId,
            messages=messages,
            inferenceConfig=inf_params
            # additionalModelRequestFields=additionalModelRequestFields,
        )

    llm_answer = resp["output"]["message"]["content"][0]["text"]
    return llm_answer

def load_file(filename):
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"File not found: {filename}")
    with open(filename, "r") as f:
        return f.read()