from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
    with path.open("w", encoding="utf-8") as file_handle:
        for item in items:
            file_handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def uniform_sample(items: list[Episode], count: int) -> list[Episode]:
    if not items:
        return []
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    sampled: list[Episode] = []
    for idx in range(count):
        picked = min(len(items) - 1, int(math.floor(idx * step)))
        sampled.append(items[picked])
    return sampled


def round_robin_sample(items: list[Episode], count: int, *, seed: int) -> list[Episode]:
    if not items:
        return []
    if len(items) <= count:
        return list(items)

    grouped: dict[str, list[Episode]] = {}
    for episode in items:
        grouped.setdefault(episode.source_file, []).append(episode)

    source_order = sorted(grouped.keys())
    if source_order:
        offset = seed % len(source_order)
        source_order = source_order[offset:] + source_order[:offset]

    positions = {source: 0 for source in source_order}
    sampled: list[Episode] = []
    while len(sampled) < count:
        progressed = False
        for source in source_order:
            position = positions[source]
            pool = grouped[source]
            if position >= len(pool):
                continue
            sampled.append(pool[position])
            positions[source] = position + 1
            progressed = True
            if len(sampled) >= count:
                break
        if not progressed:
            break
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


def snapshot_hash(input_files: list[dict]) -> str:
    payload = json.dumps(input_files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dataset_stats(path: Path, records: list[dict]) -> dict:
    source_counter = Counter(str(record.get("source_file") or "") for record in records)
    top_distribution = [
        {"source_file": source_file, "count": count}
        for source_file, count in source_counter.most_common(10)
    ]
    return {
        "path": str(path),
        "count": len(records),
        "unique_source_files": len(source_counter),
        "top_source_distribution": top_distribution,
    }


def add_dataset(summary: dict[str, object], dataset_name: str, out_path: Path, records: list[dict]) -> None:
    write_jsonl(out_path, records)
    datasets = summary["datasets"]
    assert isinstance(datasets, dict)
    datasets[dataset_name] = dataset_stats(out_path, records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build benchmark datasets from long novel text files.")
    parser.add_argument("--input-dir", default="test_files", help="Directory containing source txt files")
    parser.add_argument("--output-dir", default="verify/datasets", help="Output directory")
    parser.add_argument("--inject-sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--diversity-profile", choices=("basic", "max"), default="max")
    args = parser.parse_args()

    random.seed(args.seed)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    files = sorted(input_dir.glob("*.txt"))
    if len(files) < 1:
        raise SystemExit(f"no txt files in {input_dir}")

    file_snapshot: list[dict] = []
    for src in files:
        stat = src.stat()
        file_snapshot.append(
            {
                "file": src.name,
                "size_bytes": int(stat.st_size),
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    diversity_cuts = [200] if args.diversity_profile == "basic" else [200, 400, 800]
    summary: dict[str, object] = {
        "input_files": [],
        "source_snapshot_hash": snapshot_hash(file_snapshot),
        "build_options": {
            "seed": args.seed,
            "inject_sample_size": args.inject_sample_size,
            "diversity_profile": args.diversity_profile,
        },
        "datasets": {},
        "growth_cuts": [50, 100, 200, 400, 800],
        "diversity_cuts": diversity_cuts,
    }

    all_base_episodes: list[Episode] = []
    for src in files:
        text, enc = read_text_auto(src)
        episodes = split_episodes(text, source_file=src.name)
        all_base_episodes.extend(episodes)

        records = [to_record(src.stem, ep, content=ep.content) for ep in episodes]
        add_dataset(summary, src.stem, output_dir / f"{src.stem}.jsonl", records)

        stat = src.stat()
        summary["input_files"].append(
            {
                "file": src.name,
                "encoding": enc,
                "size_bytes": int(stat.st_size),
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "episodes": len(episodes),
            }
        )

    if not all_base_episodes:
        raise SystemExit(f"no episodes extracted from files in {input_dir}")

    sampled = uniform_sample(all_base_episodes, args.inject_sample_size)
    inject_kinds = ["age", "job", "talent", "time", "affiliation", "relation", "death", "place"]
    inject_records: list[dict] = []
    control_records: list[dict] = []
    for idx, episode in enumerate(sampled):
        kind = inject_kinds[idx % len(inject_kinds)]
        inject_records.append(
            to_record(
                "DS-INJECT-C",
                episode,
                content=inject_conflict_text(episode.content, kind),
                injected_kind=kind,
            )
        )
        control_records.append(to_record("DS-CONTROL-D", episode, content=episode.content, injected_kind=None))
    add_dataset(summary, "DS-INJECT-C", output_dir / "DS-INJECT-C.jsonl", inject_records)
    add_dataset(summary, "DS-CONTROL-D", output_dir / "DS-CONTROL-D.jsonl", control_records)

    for cut in (50, 100, 200, 400, 800):
        cut_records = [to_record(f"DS-GROWTH-{cut}", ep, content=ep.content) for ep in all_base_episodes[:cut]]
        add_dataset(summary, f"DS-GROWTH-{cut}", output_dir / f"DS-GROWTH-{cut}.jsonl", cut_records)

    for cut in diversity_cuts:
        diverse_sample = round_robin_sample(all_base_episodes, cut, seed=args.seed)
        diverse_records = [to_record(f"DS-DIVERSE-{cut}", ep, content=ep.content) for ep in diverse_sample]
        add_dataset(summary, f"DS-DIVERSE-{cut}", output_dir / f"DS-DIVERSE-{cut}.jsonl", diverse_records)

    diverse_strict_sample = round_robin_sample(all_base_episodes, args.inject_sample_size, seed=args.seed)
    diverse_inject_records: list[dict] = []
    diverse_control_records: list[dict] = []
    for idx, episode in enumerate(diverse_strict_sample):
        kind = inject_kinds[idx % len(inject_kinds)]
        diverse_inject_records.append(
            to_record(
                "DS-DIVERSE-INJECT-C",
                episode,
                content=inject_conflict_text(episode.content, kind),
                injected_kind=kind,
            )
        )
        diverse_control_records.append(
            to_record(
                "DS-DIVERSE-CONTROL-D",
                episode,
                content=episode.content,
                injected_kind=None,
            )
        )
    add_dataset(summary, "DS-DIVERSE-INJECT-C", output_dir / "DS-DIVERSE-INJECT-C.jsonl", diverse_inject_records)
    add_dataset(summary, "DS-DIVERSE-CONTROL-D", output_dir / "DS-DIVERSE-CONTROL-D.jsonl", diverse_control_records)

    summary_path = output_dir / "dataset_manifest.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "summary_path": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
