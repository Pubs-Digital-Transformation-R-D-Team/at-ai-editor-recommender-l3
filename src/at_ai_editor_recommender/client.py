import aiohttp
import asyncio

async def main():
    url = "http://localhost:8011/execute_workflow"
    payload = {
        "manuscript_number": "jm-2024-02780t",
        "coden": "jmcmar",
        "manuscript_type": "Article",
        "manuscript_title": "Investigation of the ameliorative effects of amygdalin against arsenic trioxide-induced cardiac toxicity in rat",
        "manuscript_abstract": (
            "Amygdalin, recognized as vitamin B17, is celebrated for its antioxidant and anti-inflammatory prowess, "
            "which underpins its utility in averting disease and decelerating the aging process. This study ventures to elucidate "
            "the cardioprotective mechanisms of amygdalin against arsenic trioxide (ATO)-induced cardiac injury, with a spotlight "
            "on the AMP-activated protein kinase (AMPK) and sirtuin-1 (SIRT1) signaling cascade. Employing a Sprague-Dawley rat model, "
            "we administered amygdalin followed by ATO and conducted a 15-day longitudinal study. Our findings underscore the ameliorative "
            "impact of amygdalin on histopathological cardiac anomalies, a reduction in cardiac biomarkers, and an invigoration of antioxidant "
            "defenses, thereby attenuating oxidative stress and inflammation. Notably, amygdalin's intervention abrogated ATO-induced apoptosis "
            "and inflammatory cascades, modulating key proteins along the AMPK/SIRT1 pathway and significantly dampening inflammation. Collectively, "
            "these insights advocate for amygdalin's role as a guardian against ATO-induced cardiotoxicity, potentially through the activation of the "
            "AMPK/SIRT1 axis, offering a novel therapeutic vista in mitigating oxidative stress, apoptosis, and inflammation."
        )
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            print("Status:", resp.status)
            data = await resp.json()
            print("Response:", data)

if __name__ == "__main__":
    asyncio.run(main())