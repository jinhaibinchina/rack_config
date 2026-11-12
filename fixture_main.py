from App_test_fixture.fixture_app import main
import sys

if __name__ == "__main__":
    # main() 收的是参数列表，不是整条命令字符串：传字符串会被 argparse
    # 逐字符拆成 "- - s o u r c e ..."，报 unrecognized arguments。
    raise SystemExit(main(sys.argv[1:] or ["--source", "modbus"]))