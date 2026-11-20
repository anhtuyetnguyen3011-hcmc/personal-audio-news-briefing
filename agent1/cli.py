from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .models import EvaluationReport
from .s0_ingest import FEED_FILES, ingest, input_counts, write_outputs as write_articles
from .s1_cluster import cluster, evaluate_targets, write_outputs as write_stories
from .s2_extract import extract_facts, write_outputs as write_facts


def _config(args: argparse.Namespace) -> Config:
    overrides = {}
    if getattr(args, "output_dir", None):
        overrides["output_dir"] = args.output_dir
    if getattr(args, "data_dir", None):
        overrides["data_dir"] = args.data_dir
    if getattr(args, "mode", None):
        overrides["mode"] = args.mode
    if getattr(args, "hours", None):
        overrides["window_hours"] = args.hours
    if getattr(args, "config", None):
        return Config.from_file(Path(args.config), overrides)
    return Config.from_env(overrides)


def _run_s0(config: Config) -> dict[str, Path]:
    articles, report = ingest(config)
    paths = write_articles(config, articles, report)
    print(report.model_dump_json(indent=2))
    return paths


def _run_s1(config: Config) -> dict[str, Path]:
    stories, report = cluster(config)
    paths = write_stories(config, stories, report)
    print(report.model_dump_json(indent=2))
    return paths


def _run_s2(config: Config) -> dict[str, Path]:
    facts, report = extract_facts(config)
    paths = write_facts(config, facts, report)
    print(report.model_dump_json(indent=2))
    return paths


def _run_evaluate(config: Config) -> Path:
    from .s0_ingest import load_articles
    from .s1_cluster import load_stories

    articles = load_articles(config.output_dir / "articles.json")
    stories = load_stories(config.output_dir / "stories.json")
    evaluation = evaluate_targets(stories, articles)
    report = EvaluationReport(
        generated_at_utc=datetime.now(timezone.utc),
        mode=config.mode,
        targets=evaluation["targets"],
        summary=evaluation["summary"],
    )
    path = config.output_dir / "evaluation_report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(evaluation["summary"], indent=2))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent1", description="Agent 1 S0-S2 news intelligence pipeline")
    parser.add_argument("--config", help="Optional JSON config file")
    parser.add_argument("--data-dir", help="Override input data directory")
    parser.add_argument("--output-dir", help="Override output directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inspect", help="Print input feed counts and config")

    s0 = subparsers.add_parser("s0", help="Ingest and normalize articles")
    s0.add_argument("--mode", choices=("full", "daily"), default=None)
    s0.add_argument("--hours", type=int, default=None)

    subparsers.add_parser("s1", help="Cluster and dedupe articles")
    subparsers.add_parser("s2", help="Extract facts from stories")
    subparsers.add_parser("evaluate", help="Evaluate target event clusters")

    run = subparsers.add_parser("run", help="Run S0, S1, S2 and evaluation")
    run.add_argument("--mode", choices=("full", "daily"), default=None)
    run.add_argument("--hours", type=int, default=None)

    args = parser.parse_args()
    config = _config(args)

    if args.command == "inspect":
        print(json.dumps({"config": config.public(), "input_counts": input_counts(config), "feed_files": FEED_FILES}, indent=2))
    elif args.command == "s0":
        _run_s0(config)
    elif args.command == "s1":
        _run_s1(config)
    elif args.command == "s2":
        _run_s2(config)
    elif args.command == "evaluate":
        _run_evaluate(config)
    elif args.command == "run":
        _run_s0(config)
        _run_s1(config)
        _run_s2(config)
        _run_evaluate(config)


if __name__ == "__main__":
    main()
