#!/usr/bin/env python3
"""ug-videokeeper 入口"""
from config import log, DRY_RUN
from scheduler import run


def main():
    log.info("=" * 50)
    log.info("ug-videokeeper 启动")
    log.info("DRY_RUN: %s", DRY_RUN)
    log.info("=" * 50)
    run()


if __name__ == "__main__":
    main()
