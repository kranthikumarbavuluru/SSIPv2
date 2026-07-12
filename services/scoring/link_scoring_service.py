from utils.logger import logger


class LinkScoringService:

    def __init__(self):

        self.positive_keywords = {
            "scheme": 50,
            "schemes": 50,
            "programme": 45,
            "program": 45,
            "startup": 40,
            "startups": 40,
            "innovation": 35,
            "fund": 40,
            "funding": 40,
            "grant": 45,
            "seed": 35,
            "incubator": 35,
            "incubation": 35,
            "accelerator": 35,
            "challenge": 30,
            "policy": 25,
            "guideline": 25,
            "guidelines": 25,
            "pdf": 20,
            "nidhi": 40,
            "prayas": 40,
            "eir": 30,
            "tbi": 30,
            "coe": 30,
            "birac": 35,
            "meity": 30,
            "aim": 25,
            "atal": 25
        }

        self.negative_keywords = {
            "login": -100,
            "register": -100,
            "dashboard": -100,
            "profile": -100,
            "notification": -80,
            "facebook": -100,
            "twitter": -100,
            "linkedin": -100,
            "instagram": -100,
            "youtube": -80,
            "privacy": -100,
            "terms": -100,
            "contact": -60,
            "help": -40,
            "sitemap": -40,
            "logout": -100,
            "password": -100,
            "javascript:void": -100
        }

    def score_link(self, link):

        title = link.get("title", "") or ""
        url = link.get("url", "") or ""

        combined_text = f"{title} {url}".lower()

        score = 0
        matched_positive = []
        matched_negative = []

        for keyword, value in self.positive_keywords.items():
            if keyword in combined_text:
                score += value
                matched_positive.append(keyword)

        for keyword, value in self.negative_keywords.items():
            if keyword in combined_text:
                score += value
                matched_negative.append(keyword)

        if url.lower().endswith(".pdf"):
            score += 20
            matched_positive.append("pdf_file")

        score = max(0, min(score, 100))

        return {
            "title": title.strip(),
            "url": url.strip(),
            "score": score,
            "matched_positive": matched_positive,
            "matched_negative": matched_negative
        }

    def score_links(self, links):

        scored_links = []

        for link in links:
            scored = self.score_link(link)
            scored_links.append(scored)

        logger.info(f"Scored {len(scored_links)} links.")

        return scored_links

    def filter_high_score_links(self, links, minimum_score=60):

        scored_links = self.score_links(links)

        filtered_links = [
            link for link in scored_links
            if link["score"] >= minimum_score
        ]

        logger.info(
            f"Filtered {len(scored_links)} links to {len(filtered_links)} high-score links."
        )

        return filtered_links