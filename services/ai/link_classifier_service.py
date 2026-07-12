import json
from openai import OpenAI

from config import LM_STUDIO_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS
from utils.logger import logger


class LinkClassifierService:

    def __init__(self):
        self.client = OpenAI(
            base_url=LM_STUDIO_URL,
            api_key="lm-studio"
        )

        self.reject_keywords = [
            "login", "register", "dashboard", "profile", "notification",
            "facebook", "twitter", "linkedin", "instagram", "youtube",
            "privacy", "terms", "contact", "logout", "password",
            "sitemap", "help", "javascript:void", "cookie"
        ]

        self.keep_keywords = [
            "scheme", "programme", "program", "fund", "seed", "grant",
            "startup", "innovation", "incubation", "incubator",
            "accelerator", "challenge", "guideline", "guidelines",
            "policy", "support", "nidhi", "prayash", "prayas",
            "eir", "tbi", "coe", "pdf", "document"
        ]

    def pre_filter_links(self, links):
        filtered = []

        for link in links:
            title = link.get("title", "")
            url = link.get("url", "")

            combined = f"{title} {url}".lower()

            if not url:
                continue

            if url.startswith("javascript:"):
                continue

            if any(keyword in combined for keyword in self.reject_keywords):
                continue

            if any(keyword in combined for keyword in self.keep_keywords):
                filtered.append(link)

        logger.info(f"Rule filter reduced {len(links)} links to {len(filtered)} links")

        return filtered

    def classify_links(self, links):
        filtered_links = self.pre_filter_links(links)

        if not filtered_links:
            logger.info("No links left after rule filtering.")
            return {
                "useful_links": [],
                "ignored_links": []
            }

        # Limit AI input to avoid token/time waste
        filtered_links = filtered_links[:15]

        logger.info(f"Classifying {len(filtered_links)} filtered links using local AI")

        link_text = ""

        for i, link in enumerate(filtered_links, start=1):
            link_text += f"{i}. Title: {link.get('title', '')}\n"
            link_text += f"URL: {link.get('url', '')}\n\n"

        prompt = f"""
You are a Startup Scheme Link Classification Agent.

Classify only links useful for:
- startup schemes
- innovation schemes
- grants
- funds
- incubators
- accelerators
- challenges
- official guidelines
- government startup support programmes

Reject generic navigation pages.

Return raw JSON only. Do not use markdown.

JSON format:
{{
  "useful_links": [
    {{
      "title": "title",
      "url": "url",
      "category": "Scheme Page / Funding / Incubator / Challenge / Guideline / Policy / PDF / Government Resource / Other",
      "confidence": 0.0,
      "reason": "short reason"
    }}
  ],
  "ignored_links": [
    {{
      "title": "title",
      "url": "url",
      "reason": "short reason"
    }}
  ]
}}

Links:
{link_text}
"""

        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "You classify government startup scheme links into structured JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=TEMPERATURE,
            max_tokens=1000
        )

        result = response.choices[0].message.content

        try:
            data = json.loads(result)
            logger.info(f"AI classified {len(data.get('useful_links', []))} useful links")
            return data

        except json.JSONDecodeError:
            logger.error("AI returned invalid JSON")
            logger.error(result)

            return {
                "useful_links": [],
                "ignored_links": [],
                "raw_response": result
            }