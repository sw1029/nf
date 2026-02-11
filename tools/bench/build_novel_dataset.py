from __future__ import annotations

import argparse
import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

PRIMARY_EP_RE = re.compile(r"^\[(\d{1,5})\]\s*(.*)$")
SECONDARY_EP_RE = re.compile(r"^.*?-(\d{1,5})\s*$")


@dataclass
class Episode:
    source_file: str
    episode_no: int
    header: str
    content: str


def read_text_auto(path: Path) -> tuple[str, str]:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeError:
            continue
    return path.read_text(errors="ignore"), "unknown"


def split_episodes(text: str, *, source_file: str) -> list[Episode]:
    lines = text.splitlines(keepends=True)
    boundaries: list[tuple[int, int, str]] = []
    offset = 0
    for line in lines:
        line_text = line.rstrip("\r\n")
        primary = PRIMARY_EP_RE.match(line_text)
        secondary = SECONDARY_EP_RE.match(line_text) if primary is None else None
        if primary:
            boundaries.append((offset, int(primary.group(1)), line_text))
        elif secondary:
            boundaries.append((offset, int(secondary.group(1)), line_text))
        offset += len(line)

    if len(boundaries) < 2:
        # Fallback: fixed-size pseudo episodes.
        chunk = 12000
        episodes: list[Episode] = []
        start = 0
        idx = 1
        while start < len(text):
            end = min(len(text), start + chunk)
            episodes.append(
                Episode(
                    source_file=source_file,
                    episode_no=idx,
                    header=f"episode-{idx}",
                    content=text[start:end].strip(),
                )
            )
            idx += 1
            start = end
        return [ep for ep in episodes if ep.content]

    episodes: list[Episode] = []
    for idx, (start, number, header) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(text)
        content = text[start:end].strip()
        if not content:
            continue
        episodes.append(Episode(source_file=source_file, episode_no=number, header=header, content=content))
    return episodes


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def uniform_sample(items: list[Episode], count: int) -> list[Episode]:
    if not items:
        return []
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    sampled: list[Episode] = []
    for i in range(count):
        idx = min(len(items) - 1, int(math.floor(i * step)))
        sampled.append(items[idx])
    return sampled


def inject_conflict_text(base: str, kind: str) -> str:
    templates = {
        "age": "주인공의 나이는 50세였다.",
        "job": "주인공은 9서클 마법사였다.",
        "talent": "주인공은 천재였다.",
        "time": "사건은 1999년 1월 1일에 발생했다.",
        "affiliation": "주인공의 소속은 황실 기사단이었다.",
        "relation": "주인공과 A의 관계는 원수였다.",
        "death": "주인공은 이미 사망했다.",
        "place": "장소: 북부 성채",
    }
    statement = templates.get(kind, templates["age"])
    return base.rstrip() + "\n\n[INJECT]\n" + statement + "\n"


def to_record(dataset: str, episode: Episode, *, content: str, injected_kind: str | None = None) -> dict:
    return {
        "dataset": dataset,
        "source_file": episode.source_file,
        "episode_no": episode.episode_no,
        "header": episode.header,
        "content": content,
        "injected_kind": injected_kind,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build benchmark datasets from long novel text files.")
    parser.add_argument("--input-dir", default="test_files", help="Directory containing source txt files")
    parser.add_argument("--output-dir", default="verify/datasets", help="Output directory")
    parser.add_argument("--inject-sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    files = sorted(input_dir.glob("*.txt"))
    if len(files) < 1:
        raise SystemExit(f"no txt files in {input_dir}")

    summary: dict[str, object] = {
        "input_files": [],
        "datasets": {},
        "growth_cuts": [50, 100, 200, 400, 800],
    }

    all_base_episodes: list[Episode] = []
    base_outputs: list[tuple[str, Path, list[dict]]] = []
    for src in files:
        text, enc = read_text_auto(src)
        episodes = split_episodes(text, source_file=src.name)
        all_base_episodes.extend(episodes)
        dataset_name = src.stem
        records = [to_record(dataset_name, ep, content=ep.content) for ep in episodes]
        out_path = output_dir / f"{dataset_name}.jsonl"
        base_outputs.append((dataset_name, out_path, records))
        summary["input_files"].append({"file": src.name, "encoding": enc, "episodes": len(episodes)})

    for dataset_name, out_path, records in base_outputs:
        write_jsonl(out_path, records)
        summary["datasets"][dataset_name] = {"path": str(out_path), "count": len(records)}

    sampled = uniform_sample(all_base_episodes, args.inject_sample_size)
    inject_kinds = ["age", "job", "talent", "time", "affiliation", "relation", "death", "place"]
    inject_records: list[dict] = []
    control_records: list[dict] = []
    for idx, ep in enumerate(sampled):
        kind = inject_kinds[idx % len(inject_kinds)]
        inject_records.append(
            to_record(
                "DS-INJECT-C",
                ep,
                content=inject_conflict_text(ep.content, kind),
                injected_kind=kind,
            )
        )
        control_records.append(
            to_record(
                "DS-CONTROL-D",
                ep,
                content=ep.content,
                injected_kind=None,
            )
        )

    inject_path = output_dir / "DS-INJECT-C.jsonl"
    control_path = output_dir / "DS-CONTROL-D.jsonl"
    write_jsonl(inject_path, inject_records)
    write_jsonl(control_path, control_records)
    summary["datasets"]["DS-INJECT-C"] = {"path": str(inject_path), "count": len(inject_records)}
    summary["datasets"]["DS-CONTROL-D"] = {"path": str(control_path), "count": len(control_records)}

    for cut in (50, 100, 200, 400, 800):
        cut_records = [to_record(f"DS-GROWTH-{cut}", ep, content=ep.content) for ep in all_base_episodes[:cut]]
        cut_path = output_dir / f"DS-GROWTH-{cut}.jsonl"
        write_jsonl(cut_path, cut_records)
        summary["datasets"][f"DS-GROWTH-{cut}"] = {"path": str(cut_path), "count": len(cut_records)}

    summary_path = output_dir / "dataset_manifest.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "summary_path": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
