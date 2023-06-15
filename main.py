#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import signal
from wcferry import Wcf
from configuration import Config
from robot import Robot


def main():
    config = Config()
    wcf = Wcf(debug=True)

    def handler(sig, frame):
        wcf.cleanup()  # 退出前清理环境
        exit(0)

    signal.signal(signal.SIGINT, handler)

    robot = Robot(config, wcf)
    robot.LOG.info(f"正在启动机器人···, wxid: {wcf.get_self_wxid()}")

    # 机器人启动发送测试消息
    robot.sendTextMsg("机器人启动成功！", "filehelper")

    # 暴露 HTTP 接口供发送消息，需要在配置文件中取消 http 注释
    # 接口文档：http://localhost:9999/docs
    # 访问示例：
    # 1. 浏览器访问：http://localhost:9999/send?msg=hello%20world&receiver=filehelper
    # 2. curl -X 'GET' 'http://localhost:9999/send?msg=hello%20world&receiver=filehelper' -H 'accept: application/json'
    robot.enableHTTP()

    # 接收消息
    robot.enableRecvMsg()

    # 每天 7 点发送天气预报
    robot.onEveryTime("07:00", weather_report, robot=robot)

    # 每天 7:30 发送新闻
    robot.onEveryTime("07:30", robot.newsReport)

    # 让机器人一直跑
    robot.keepRunningAndBlockProcess()


if __name__ == "__main__":
    main()
