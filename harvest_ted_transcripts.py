#!/usr/bin/env python3
"""
TED Talks Offline Transcripts Harvester & Topic Classifier.
Downloads the complete IWSLT English transcripts dataset via HuggingFace datasets-server REST API.
Indexes and categorizes all transcripts into the exact 46 topics requested by the user.
Saves clean offline Markdown files, a searchable JSON catalog, and a SQLite full-text search DB into:
~/KnowRepo1/06_History_Law_and_Civics/ted_talks_transcripts/
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("KGS_REPO_ROOT", os.path.expanduser("~/KnowRepo1")))
OUTPUT_DIR = REPO_ROOT / "06_History_Law_and_Civics" / "ted_talks_transcripts"
MANAGER_PY = BASE_DIR / "repo_manager.py"

USER_TOPICS = [
    "inclusion", "wildlife", "life", "play", "ai", "pandemic", "capitalism",
    "emotions", "leadership", "conservation", "tech", "family", "performance",
    "sustainability", "money", "relationships", "microbes", "blockchain",
    "policy", "energy", "human-rights", "community", "business", "democracy",
    "innovation", "agriculture", "society", "pollution", "investing", "data",
    "travel", "law", "entrepreneur", "machine-learning", "humanity", "trees",
    "success", "algorithm", "vulnerability", "empathy", "friendship",
    "communication", "cryptocurrency", "nature", "pain", "electricity"
]

TOPIC_KEYWORDS = {
    "inclusion": ["inclusion", "diversity", "disability", "accessible", "marginalized"],
    "wildlife": ["wildlife", "species", "animal", "predator", "habitat", "biodiversity"],
    "life": ["life", "living", "existence", "mortality", "purpose", "meaning of life"],
    "play": ["play", "game", "toy", "childhood", "fun", "gamification"],
    "ai": ["artificial intelligence", "ai", "neural network", "machine intelligence", "deep learning"],
    "pandemic": ["pandemic", "virus", "epidemic", "quarantine", "outbreak", "pathogen"],
    "capitalism": ["capitalism", "capitalist", "market economy", "wealth", "corporation"],
    "emotions": ["emotion", "feeling", "anger", "grief", "joy", "sadness", "anxiety"],
    "leadership": ["leadership", "leader", "manage", "inspire", "team", "organization"],
    "conservation": ["conservation", "preserve", "endangered", "rainforest", "marine life"],
    "tech": ["technology", "digital", "internet", "software", "hardware", "cyber"],
    "family": ["family", "parent", "mother", "father", "children", "sibling"],
    "performance": ["performance", "athletic", "musician", "performer", "stage", "acting"],
    "sustainability": ["sustainability", "sustainable", "renewable", "carbon footprint", "recycling"],
    "money": ["money", "finance", "currency", "debt", "income", "economic"],
    "relationships": ["relationship", "partner", "marriage", "dating", "couple", "interpersonal"],
    "microbes": ["microbe", "bacteria", "microbiome", "fungi", "organism", "cellular"],
    "blockchain": ["blockchain", "ledger", "decentralized", "smart contract", "crypto"],
    "policy": ["policy", "regulation", "legislation", "public policy", "governance"],
    "energy": ["energy", "solar", "wind power", "grid", "electricity", "fuel"],
    "human-rights": ["human rights", "equality", "civil rights", "freedom", "justice", "oppression"],
    "community": ["community", "neighborhood", "solidarity", "civic", "social cohesion"],
    "business": ["business", "company", "startup", "commerce", "enterprise", "industry"],
    "democracy": ["democracy", "democratic", "election", "voting", "citizen", "parliament"],
    "innovation": ["innovation", "invention", "breakthrough", "design", "creative", "prototype"],
    "agriculture": ["agriculture", "farming", "crop", "harvest", "soil", "livestock", "food production"],
    "society": ["society", "societal", "cultural", "social norm", "civilization"],
    "pollution": ["pollution", "plastic", "toxic", "waste", "emissions", "smog", "contamination"],
    "investing": ["investing", "investor", "stock market", "portfolio", "venture capital", "capital"],
    "data": ["data", "statistics", "analytics", "big data", "metrics", "dataset"],
    "travel": ["travel", "journey", "exploration", "tourism", "voyage", "destination"],
    "law": ["law", "legal", "court", "attorney", "judge", "constitution", "trial"],
    "entrepreneur": ["entrepreneur", "founder", "venture", "pitch", "business plan"],
    "machine-learning": ["machine learning", "ml", "algorithm", "supervised", "training model"],
    "humanity": ["humanity", "human condition", "mankind", "human species", "empathy"],
    "trees": ["tree", "forest", "canopy", "timber", "woodland", "reforestation"],
    "success": ["success", "achievement", "goal", "accomplish", "excellence", "triumph"],
    "algorithm": ["algorithm", "computational", "sorting", "algorithmic", "code"],
    "vulnerability": ["vulnerability", "vulnerable", "shame", "courage", "exposure"],
    "empathy": ["empathy", "compassion", "understanding", "perspective", "sympathy"],
    "friendship": ["friendship", "friend", "companion", "camaraderie", "connection"],
    "communication": ["communication", "speech", "dialogue", "listening", "conversation", "message"],
    "cryptocurrency": ["cryptocurrency", "bitcoin", "ethereum", "wallet", "crypto asset"],
    "nature": ["nature", "natural world", "wilderness", "mountains", "rivers", "ocean"],
    "pain": ["pain", "chronic pain", "suffering", "injury", "healing", "ache"],
    "electricity": ["electricity", "voltage", "current", "circuit", "electric power", "watts"]
}


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name)
    name = re.sub(r'\s+', '_', name).strip('_-')
    return name[:80] or "untitled_talk"


def classify_text(text: str) -> list:
    text_lower = text.lower()
    matched = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += text_lower.count(kw)
        if score > 0:
            matched.append((topic, score))
    matched.sort(key=lambda x: x[1], reverse=True)
    return [t[0] for t in matched]


def main():
    print("=" * 70)
    print("Harvesting IWSLT TED Talks Transcripts Dataset into ~/KnowRepo1")
    print(f"Output Directory: {OUTPUT_DIR}")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    by_topic_dir = OUTPUT_DIR / "by_topic"
    by_topic_dir.mkdir(parents=True, exist_ok=True)
    for topic in USER_TOPICS:
        (by_topic_dir / topic).mkdir(parents=True, exist_ok=True)

    db_path = OUTPUT_DIR / "ted_transcripts.sqlite3"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS talks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            snippet TEXT,
            full_text TEXT,
            topics TEXT,
            word_count INTEGER
        )
    """)
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS talks_fts USING fts5(title, full_text, topics, content=talks, content_rowid=id)")
    conn.commit()

    base_api = "https://datasets-server.huggingface.co/rows?dataset=vietgpt%2Fted_talks_iwslt_en&config=default&split=train"
    offset = 0
    limit = 100
    total_talks = 2293
    collected = 0

    talks_catalog = []

    while offset < total_talks:
        url = f"{base_api}&offset={offset}&limit={limit}"
        print(f"  [+] Fetching rows {offset} to {min(offset + limit, total_talks)}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
                rows = data.get("rows", [])
                if not rows:
                    break

                for row_data in rows:
                    raw_text = row_data.get("row", {}).get("text", "").strip()
                    if not raw_text or len(raw_text) < 100:
                        continue

                    collected += 1
                    first_sentence = raw_text.split(".")[0].strip()
                    title = f"Talk {collected}: {first_sentence[:60]}"
                    words = len(raw_text.split())

                    matched_topics = classify_text(raw_text)
                    primary_topic = matched_topics[0] if matched_topics else "society"

                    # Save into SQLite
                    cur.execute(
                        "INSERT INTO talks (id, title, snippet, full_text, topics, word_count) VALUES (?, ?, ?, ?, ?, ?)",
                        (collected, title, first_sentence, raw_text, ",".join(matched_topics), words)
                    )
                    cur.execute(
                        "INSERT INTO talks_fts (rowid, title, full_text, topics) VALUES (?, ?, ?, ?)",
                        (collected, title, raw_text, ",".join(matched_topics))
                    )

                    talk_record = {
                        "id": collected,
                        "title": title,
                        "words": words,
                        "topics": matched_topics[:4],
                    }
                    talks_catalog.append(talk_record)

                    # Write clean Markdown copy into primary matched user topic folders
                    for top in matched_topics[:2]:
                        if top in USER_TOPICS:
                            md_file = by_topic_dir / top / f"{collected:04d}_{sanitize_filename(first_sentence)}.md"
                            if not md_file.exists():
                                content = f"# {title}\n\n**Topics:** {', '.join(matched_topics[:5])}  \n**Word Count:** {words}\n\n---\n\n{raw_text}\n"
                                md_file.write_text(content, encoding="utf-8")

                conn.commit()
                offset += limit
                time.sleep(0.5)
        except Exception as e:
            print(f"  [!] Batch fetch warning at offset {offset}: {e}")
            time.sleep(2)
            offset += limit

    conn.close()

    # Save master catalog JSON and README
    (OUTPUT_DIR / "ted_catalog.json").write_text(json.dumps(talks_catalog, indent=2), encoding="utf-8")
    readme_content = f"""# TED Talks Offline Transcripts Archive

Complete offline transcripts of {collected} curated TED Talks, classified into your requested topic collections:

## Collections & Categories
- **Database:** Full-text searchable SQLite database (`ted_transcripts.sqlite3`)
- **Catalog:** JSON registry (`ted_catalog.json`)
- **Organized Folders:**
"""
    for t in sorted(USER_TOPICS):
        cnt = len(list((by_topic_dir / t).glob("*.md")))
        readme_content += f"- [`{t}`](./by_topic/{t}/) ({cnt} talks)\n"

    (OUTPUT_DIR / "README.md").write_text(readme_content, encoding="utf-8")
    print(f"\n[+] Successfully harvested {collected} talks into {OUTPUT_DIR}")
    print(f"[+] Total size footprint: {sum(f.stat().st_size for f in OUTPUT_DIR.rglob('*') if f.is_file()) / (1024*1024):.2f} MB")

    # Update repo index
    print("[+] Re-indexing Knowledge Repository catalog...")
    subprocess.run([sys.executable, str(MANAGER_PY), "--repo", str(REPO_ROOT), "index"])


if __name__ == "__main__":
    main()
