from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

DEFAULT_MODEL_ID = "nli-lite-v1"
DEFAULT_REPO_ID = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
DEFAULT_REVISION = "acf08db83390e23428c560cb578a865b39196993"
MODEL_MANIFEST_FILENAME = "nf_model_manifest.json"
ALLOW_PATTERNS = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "vocab.json",
    "merges.txt",
    "spiece.model",
    "sentencepiece.bpe.model",
    "model.safetensors",
    "pytorch_model.bin",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a real local NLI model into the Codex model store.")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--target-root", default="data/models")
    parser.add_argument("--max-length", type=int, default=512)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_root = Path(args.target_root)
    target_dir = target_root / str(args.model_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    snapshot_download(
        repo_id=str(args.repo_id),
        revision=str(args.revision),
        local_dir=str(target_dir),
        allow_patterns=list(ALLOW_PATTERNS),
    )

    config_path = target_dir / "config.json"
    label_order = ["contradiction", "neutral", "entailment"]
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            id2label = config.get("id2label")
            if isinstance(id2label, dict):
                ordered: list[str] = []
                for idx in sorted((int(key) for key in id2label.keys())):
                    ordered.append(str(id2label[str(idx)]))
                if len(ordered) >= 3:
                    label_order = ordered[:3]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    manifest = {
        "backend": "hf_sequence_classification",
        "task": "nli",
        "framework": "transformers",
        "source_repo": str(args.repo_id),
        "source_revision": str(args.revision),
        "label_order": label_order,
        "max_length": int(args.max_length),
    }
    manifest_path = target_dir / MODEL_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "model_id": str(args.model_id),
                "repo_id": str(args.repo_id),
                "revision": str(args.revision),
                "target_dir": str(target_dir),
                "manifest_path": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
