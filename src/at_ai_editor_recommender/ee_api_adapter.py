from abc import ABC, abstractmethod
import aiohttp
from jinja2 import Template
import os
import logging
import json

class EeApiAdapter(ABC):
    def __init__(self, base_url):
        self.base_url = base_url
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def fetch_raw_data(self, manuscript_number: str, journal_id: str = None):
        pass

    @abstractmethod
    async def get_manuscript_with_editors(self, manuscript_number: str):
        pass


class EeJsonApiAdapter(EeApiAdapter):

    def __init__(self, base_url):
        super().__init__(base_url)
        self.manuscript_info_template = None
        self.available_editors_template = None

        # Assume the project root is one directory above src
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        prompts_root = os.path.join(project_root, "prompts")
        manuscript_info_path = os.path.join(prompts_root, "manuscript_information", "manuscript_information.jinja2")
        available_editors_path = os.path.join(prompts_root, "available_editors", "available_editors.jinja2")
        
        if os.path.exists(manuscript_info_path):
            with open(manuscript_info_path, 'r') as f:
                self.manuscript_info_template = Template(f.read())
            logging.info(f"Loaded manuscript info template: {manuscript_info_path}")
            
        if os.path.exists(available_editors_path):
            with open(available_editors_path, 'r') as f:
                self.available_editors_template = Template(f.read())
            logging.info(f"Loaded available editors template: {available_editors_path}")

    async def fetch_raw_data(self, manuscript_number: str, journal_id: str):
        url = f"{self.base_url}"
        data = {
            "manuscript_id": manuscript_number,
            "journal_id": journal_id
        }
        self.logger.info(f"Fetching EE data from URL: {url} with data: {data}")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                try:
                    resp.raise_for_status()
                    return await resp.text()
                except aiohttp.ClientResponseError as e:
                    # Read response body and attach it to the exception
                    response_body = await resp.text()
                    e.response_text = response_body
                    raise

    async def render_manuscript_information(self, manuscript_info):
        return self.manuscript_info_template.render(**manuscript_info)
    

    async def render_available_editors(self, available_editors):
        return self.available_editors_template.render(**available_editors)

    async def get_manuscript_with_editors(self, manuscript_number: str, journal_id: str):
        raw = await self.fetch_raw_data(manuscript_number, journal_id)

        data = json.loads(raw)

        # render manuscript
        manuscript_info = data.get("data", {}).get("processedData", {})
        manuscript_info_rendered = None

        if manuscript_info:
            manuscript_info_rendered = await self.render_manuscript_information(manuscript_info)

        available_editors_rendered = None
        # render editors
        available_editors = data.get("data", {}).get("processedData", {})
        if available_editors:
            available_editors_rendered = await self.render_available_editors(available_editors)

        return { "manuscript_information": manuscript_info_rendered, "available_editors": available_editors_rendered }


class EeMarkdownApiAdapter(EeApiAdapter):
    async def fetch_raw_data(self, manuscript_number: str, journal_id: str = None):
        url = f"{self.base_url}/{manuscript_number}"
        self.logger.info(f"Fetching EE data from URL: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                try:
                    resp.raise_for_status()
                    return await resp.json()
                except aiohttp.ClientResponseError as e:
                    # Read response body and attach it to the exception
                    response_body = await resp.text()
                    e.response_text = response_body
                    raise

    async def get_manuscript_with_editors(self, manuscript_number: str, journal_id: str = None):
        raw = await self.fetch_raw_data(manuscript_number)
        # { "manuscript_information": ..., "available_editors": ... }

        return raw



def get_adapter_for_url(url: str) -> EeApiAdapter:
    if "editor_assignment_protocol" in url:
        return EeMarkdownApiAdapter(url)
    else:
        return EeJsonApiAdapter(url)