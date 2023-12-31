# -*- coding: utf-8 -*-
import logging
import re
import time
import xml.etree.ElementTree as ET
import os

from configuration import Config
from func_chatgpt import ChatGPT
from func_chengyu import cy
from func_http import Http
from func_news import NEWS
from job_mgmt import Job
from wcferry import Wcf, WxMsg


class Robot(Job):
    """个性化自己的机器人
    """

    def __init__(self, config: Config, wcf: Wcf) -> None:
        self.wcf = wcf
        self.config = config
        self.LOG = logging.getLogger("Robot")
        self.wxid = self.wcf.get_self_wxid()
        self.allContacts = self.getAllContacts() # 新获取名单的函数
        self.chat = None
        self.reloadconfig()
        chatgpt = self.config.CHATGPT
        if chatgpt:
            self.chat = ChatGPT(chatgpt.get("key"), chatgpt.get("api"), chatgpt.get("proxy"), chatgpt.get("prompt"))
    

    def reloadconfig(self):
        pwd = os.path.dirname(os.path.abspath(__file__))
        """寻找模糊匹配的群组，放入接收的组变量
        """
        self.LOG.info(f">>> 模糊匹配群 <<<  {self.config.CHATROOMS}") 
        for wxID, wxName in self.allContacts.items():
            if re.search(r"@chatroom", wxID, re.M|re.I):
                if re.search(self.config.CHATROOMS, wxName, re.M|re.I):
                    self.LOG.info(f">>> {wxID} -> {wxName}")
                    self.config.GROUPS.append(wxID)
        
        """寻找要开启的函数列表，引入自定义扩展
        """
        for ID,Func in self.config.COMMANDS.items():
            cmdFunc = Func.lower()
            cmdFunc = "func_" + cmdFunc if not re.search(r"^func_", cmdFunc) else cmdFunc
            cmdFunc = cmdFunc + ".py"   if not re.search(r".py$", cmdFunc) else cmdFunc

            try:
                with open(f"{pwd}/{cmdFunc}", "rb") as fp:
                    cmdFunc = re.split(".py", cmdFunc)[0].lower()

                    try:
                        self.LOG.info(f">>> from {cmdFunc} import {Func}")
                        #exec(f"from {cmdFunc} import {Func}")
                    except Exception as e:
                        self.LOG.error(f">>> {e}")
            except FileNotFoundError:
                self.LOG.error(f">>> 无法找到{ID}这个模块({cmdFunc})")
 

    def toAt(self, msg: WxMsg) -> bool:
        """处理被 @ 消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        return self.toChitchat(msg)

    def toChengyu(self, msg: WxMsg) -> bool:
        """
        处理成语查询/接龙消息
        :param msg: 微信消息结构
        :return: 处理状态，`True` 成功，`False` 失败
        """
        status = False
        texts = re.findall(r"^([#|?|？])(.*)$", msg.content)
        # [('#', '天天向上')]
        if texts:
            flag = texts[0][0]
            text = texts[0][1]
            if flag == "#":  # 接龙
                if cy.isChengyu(text):
                    rsp = cy.getNext(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True
            elif flag in ["?", "？"]:  # 查词
                if cy.isChengyu(text):
                    rsp = cy.getMeaning(text)
                    if rsp:
                        self.sendTextMsg(rsp, msg.roomid)
                        status = True

        return status

    def toChitchat(self, msg: WxMsg) -> bool:
        """闲聊，接入 ChatGPT
        """
        if not self.chat:  # 没接 ChatGPT，固定回复
            rsp = "好的，等我一下=="
        else:  # 接了 ChatGPT，智能回复
            q = re.sub(r"@.*?[\u2005|\s]", "", msg.content).replace(" ", "")
            rsp = self.chat.get_answer(q, (msg.roomid if msg.from_group() else msg.sender))

        if rsp:
            if msg.from_group():
                self.sendTextMsg(rsp, msg.roomid, msg.sender)
            else:
                self.sendTextMsg(rsp, msg.sender)

            return True
        else:
            self.LOG.error(f"无法从 ChatGPT 获得答案")
            return False

    def processMsg(self, msg: WxMsg) -> None:
        """当接收到消息的时候，会调用本方法。如果不实现本方法，则打印原始消息。
        此处可进行自定义发送的内容,如通过 msg.content 关键字自动获取当前天气信息，并发送到对应的群组@发送者
        群号：msg.roomid  微信ID：msg.sender  消息内容：msg.content
        content = "xx天气信息为："
        receivers = msg.roomid
        self.sendTextMsg(content, receivers, msg.sender)
        """

        # 群聊消息
        if msg.from_group():
            # 如果在群里被 @
            if msg.roomid not in self.config.GROUPS:  # 不在配置的响应的群列表里，忽略
                return

            if msg.is_at(self.wxid):   # 被@
                self.toAt(msg)

            else:                # 其他消息
                self.toChengyu(msg)

            return  # 处理完群聊信息，后面就不需要处理了

        # 非群聊信息，按消息类型进行处理
        if msg.type == 37:     # 好友请求
            self.autoAcceptFriendRequest(msg)

        elif msg.type == 10000:  # 系统信息
            self.sayHiToNewFriend(msg)

        elif msg.type == 0x01:   # 文本消息
            # 让配置加载更灵活，自己可以更新配置。也可以利用定时任务更新。
            if msg.from_self():
                #if msg.content == "^更新$":
                if re.findall(r"更新", msg.content):
                    self.config.reload()
                    self.reloadconfig()
                    self.LOG.info(f">>> 收到文本更新了。")
            else:
                self.toChitchat(msg)  # 闲聊

    def onMsg(self, msg: WxMsg) -> int:
        try:
            self.LOG.info(msg)  # 打印信息
            self.processMsg(msg)
        except Exception as e:
            self.LOG.error(e)

        return 0

    def enableRecvMsg(self) -> None:
        self.wcf.enable_recv_msg(self.onMsg)

    def sendTextMsg(self, msg: str, receiver: str, at_list: str = "") -> None:
        """ 发送消息
        :param msg: 消息字符串
        :param receiver: 接收人wxid或者群id
        :param at_list: 要@的wxid, @所有人的wxid为：nofity@all
        """
        # msg 中需要有 @ 名单中一样数量的 @
        ats = ""
        if at_list:
            wxids = at_list.split(",")
            for wxid in wxids:
                # 这里偷个懒，直接 @昵称。有必要的话可以通过 MicroMsg.db 里的 ChatRoom 表，解析群昵称
                ats += f" @{self.allContacts.get(wxid, '')}"

        # {msg}{ats} 表示要发送的消息内容后面紧跟@，例如 北京天气情况为：xxx @张三，微信规定需这样写，否则@不生效
        if ats == "":
            self.LOG.info(f"To {receiver}: {msg}")
            self.wcf.send_text(f"{msg}", receiver, at_list)
        else:
            self.LOG.info(f"To {receiver}: {ats}\r{msg}")
            self.wcf.send_text(f"{ats}\n\n{msg}", receiver, at_list)

    def getAllContacts(self) -> dict:
        """
        获取联系人（包括好友、公众号、服务号、群成员……）
        格式: {"wxid": "NickName"}
        """
        contacts = self.wcf.query_sql("MicroMsg.db", "SELECT UserName, NickName, Remark FROM Contact;")
        return {contact["UserName"]: contact["Remark"] if contact["Remark"] else contact["NickName"] for contact in contacts}

    def keepRunningAndBlockProcess(self) -> None:
        """
        保持机器人运行，不让进程退出
        """
        while True:
            self.runPendingJobs()
            time.sleep(1)

    def autoAcceptFriendRequest(self, msg: WxMsg) -> None:
        try:
            xml = ET.fromstring(msg.content)
            v3 = xml.attrib["encryptusername"]
            v4 = xml.attrib["ticket"]
            scene = xml.attrib["scene"]
            self.wcf.accept_new_friend(v3, v4, scene)

        except Exception as e:
            self.LOG.error(f"同意好友出错：{e}")

    def sayHiToNewFriend(self, msg: WxMsg) -> None:
        nickName = re.findall(r"你已添加了(.*)，现在可以开始聊天了。", msg.content)
        if nickName:
            # 添加了好友，更新好友列表
            self.allContacts[msg.sender] = nickName[0]
            self.sendTextMsg(f"Hi {nickName[0]}，我自动通过了你的好友请求。", msg.sender)

    def enableHTTP(self) -> None:
        """暴露 HTTP 发送消息接口供外部调用，不配置则忽略"""
        c = self.config.HTTP
        if not c:
            return

        home = "https://github.com/lich0821/WeChatFerry"
        http = Http(wcf=self.wcf,
                    title="API for send text",
                    description=f"Github: <a href='{home}'>WeChatFerry</a>",)
        Http.start(http, c["host"], c["port"])
        self.LOG.info(f"HTTP listening on http://{c['host']}:{c['port']}")

    def newsReport(self) -> None:
        receivers = self.config.NEWS
        if not receivers:
            return

        news = NEWS().get_important_news()
        for r in receivers:
            self.sendTextMsg(news, r)
