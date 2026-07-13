#!/usr/bin/env python3
"""ug-videokeeper 入口"""
import sys
from config import log, DRY_RUN
from checks import run_all
from scheduler import run


def main():
    if "--report" in sys.argv:
        from analytics.reporter import generate_report
        try:
            year_args = [a for a in sys.argv[1:] if a != "--report"]
            year = int(year_args[0]) if year_args else 2026
        except (ValueError, IndexError):
            log.error("用法: python main.py --report <year>（year 必须是数字）")
            return
        run_all()  # 先跑一致性检查，确保缓存/DB 状态正确
        generate_report("annual", year)
        return

    if "--serve" in sys.argv:
        from analytics.server import start_server
        run_all()
        start_server()
        return

    run_all()
    log.info("=" * 50)
    log.info("ug-videokeeper 启动")
    log.info("DRY_RUN: %s", DRY_RUN)
    log.info("=" * 50)
    run()


if __name__ == "__main__":
    main()
