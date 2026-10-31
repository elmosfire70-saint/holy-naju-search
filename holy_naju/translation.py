# 원문 문단과 모델·프롬프트 버전에 연결된 한국어 번역을 보관하고 재사용한다.
import hashlib
import json
from uuid import uuid4

from holy_naju.local_models import LocalModelError, OllamaClient
from holy_naju.storage import encode, now

PROMPT_REVISION = "ko-faithful-json-3"


def get_translation(library, translation_id):
    row = library.db.execute("SELECT t.*,p.version_id,p.text AS original,p.locator FROM translations t "
                             "JOIN passages p ON p.id=t.passage_id WHERE t.id=?", (translation_id,)).fetchone()
    if row is None:
        raise KeyError(translation_id)
    result = dict(row)
    result["model_profile"] = json.loads(result["model_profile"])
    result["locator"] = json.loads(result["locator"])
    return result


def translate_passage(library, passage_id, *, client=None, model="qwen3.5:9b", refresh=False):
    row = library.db.execute("SELECT p.*,e.language FROM passages p JOIN document_versions v ON v.id=p.version_id "
                             "JOIN editions e ON e.id=v.edition_id WHERE p.id=?", (passage_id,)).fetchone()
    if row is None:
        raise KeyError(passage_id)
    if row["language"].lower().split("-")[0] in {"ko", "kor"}:
        return {"passage_id": passage_id, "version_id": row["version_id"], "original": row["text"],
                "text": row["text"], "kind": "original", "reused": True, "locator": json.loads(row["locator"])}
    if len(row["text"]) > 12000:
        raise LocalModelError("passage_too_long_for_translation")
    client = client or OllamaClient()
    profile = {"name": model, "digest": None}
    source_hash = hashlib.sha256(row["text"].encode()).hexdigest()
    try:
        profile = {**client.profile(model, "completion"), "num_ctx": 8192, "temperature": 0, "seed": 0, "num_predict": 4096}
        cached = None if refresh else library.db.execute(
            "SELECT id FROM translations WHERE passage_id=? AND source_hash=? AND model_profile=? "
            "AND prompt_revision=? AND status='completed' ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (passage_id, source_hash, encode(profile), PROMPT_REVISION)).fetchone()
        if cached:
            result = get_translation(library, cached["id"])
            result["reused"] = True
            return result
        text = client.translate(row["text"], profile)
        if not isinstance(text, str) or not text.strip():
            raise LocalModelError("empty_translation")
    except LocalModelError as error:
        with library.db:
            library.db.execute("INSERT INTO translations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (str(uuid4()), passage_id, source_hash, "ko", encode(profile), PROMPT_REVISION,
                                None, "failed", "unreviewed", str(error), now()))
        raise
    translation_id = str(uuid4())
    with library.db:
        library.db.execute("INSERT INTO translations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (translation_id, passage_id, source_hash, "ko", encode(profile), PROMPT_REVISION,
                            text, "completed", "unreviewed", None, now()))
    result = get_translation(library, translation_id)
    result["reused"] = False
    return result
