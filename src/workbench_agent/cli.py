from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .client import WorkbenchClient
from .config import AgentConfig, default_config_path, load_config, load_token
from .errors import AgentError
from .research.codex_runner import CodexResearchRunner
from .research.models import ResearchResult
from .research.service import ResearchService
from .service import AgentService, DoctorReport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workbench-agent",
        description="Run outbound Personal Workbench capabilities.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="JSON config path (default: %(default)s)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check configuration and connectivity without writing")
    commands.add_parser("heartbeat", help="Upsert this device")
    sync = commands.add_parser("sync", help="Upsert the device and configured sources")
    sync.add_argument("--dry-run", action="store_true", help="Validate and print without POSTs")
    observe = commands.add_parser("observe-run", help="Submit one workbench-run.json manifest")
    observe.add_argument("--project", required=True, help="Configured local project key")
    observe.add_argument("--manifest", required=True, type=Path, help="Run manifest path")
    research = commands.add_parser("research", help="Run paper research tasks")
    research_commands = research.add_subparsers(
        dest="research_command", required=True
    )
    research_run = research_commands.add_parser("run", help="Run one research task")
    research_run.add_argument("task_key", help="Local research task key")
    research_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Research and validate without writing to Workbench",
    )
    return parser


def _print_doctor(config: AgentConfig, report: DoctorReport) -> None:
    print(f"Workbench Agent {__version__}")
    print("\nConfig")
    print("  parsed                         OK")
    print("\nDevice")
    print(f"  {config.device.id:<30} OK")
    print("\nServer")
    print(
        f"  {config.server.url:<30} "
        f"{'OK' if report.server_reachable else 'FAIL'}"
    )
    print(f"  token                         {'OK' if report.token_present else 'FAIL'}")
    if report.server_error:
        print(f"  detail                        {report.server_error}")
    print("\nProjects")
    if not report.projects:
        print("  (none)")
    for check in report.projects:
        print(f"  {check.project.key}")
        print(f"  {check.project.path:<30} {'OK' if check.ok else 'FAIL'}")
    print(f"\nResult: {'healthy' if report.healthy else 'unhealthy'}")


def _print_dry_run(config: AgentConfig) -> None:
    print("Dry run: no HTTP writes")
    print(
        "Device heartbeat: "
        f"device_id={config.device.id!r}, name={config.device.name!r}, "
        f"agent_version={__version__!r}"
    )
    for project in config.projects:
        print(
            f"Source {project.key}: project_id={project.project_id!r}, "
            f"source_type={project.source_type!r}, source_key={project.source_key!r}, "
            f"device_id={config.device.id!r}, local_path={project.path!r}"
        )


def _print_research(result: ResearchResult, *, dry_run: bool) -> None:
    print("Research completed")
    print(f"\nTask: {result.task_key}")
    print(f"Run: {result.run_key}")
    print(f"Query plan: {len(result.query_plan)}")
    print(f"Recommended: {len(result.papers)}")
    for index, paper in enumerate(result.papers, 1):
        relevance = (
            "unknown"
            if paper.relevance_score is None
            else f"{paper.relevance_score:.2f}"
        )
        print(f"\n{index}. {paper.title}")
        print(f"   relevance: {relevance}")
    if dry_run:
        print("\nDry run: no Workbench write")
    else:
        print("\nWorkbench ingest accepted")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "research":
            token = None if args.dry_run else load_token(config)
            with WorkbenchClient(config.server.url, token) as client:
                result, _ = ResearchService(
                    client, CodexResearchRunner()
                ).run(args.task_key, dry_run=args.dry_run)
            _print_research(result, dry_run=args.dry_run)
            return 0
        if args.command == "sync" and args.dry_run:
            with WorkbenchClient(config.server.url, None) as client:
                AgentService(config, client).sync(dry_run=True)
            _print_dry_run(config)
            return 0

        token = os.environ.get(config.server.token_env)
        if args.command != "doctor":
            token = load_token(config)
        with WorkbenchClient(config.server.url, token) as client:
            service = AgentService(config, client)
            if args.command == "doctor":
                report = service.doctor(token_present=bool(token))
                _print_doctor(config, report)
                return 0 if report.healthy else 1
            if args.command == "heartbeat":
                service.heartbeat()
                print(f"Heartbeat accepted for {config.device.id}")
                return 0
            if args.command == "sync":
                sources = service.sync()
                print(f"Synced device and {len(sources)} project source(s)")
                for key, source_id in sources.items():
                    print(f"  {key}: {source_id}")
                return 0
            if args.command == "observe-run":
                service.observe_run(args.project, args.manifest)
                print(f"Run observation accepted for project {args.project}")
                return 0
    except AgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2
