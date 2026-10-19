# -*- coding: utf-8 -*-
"""单实例：第二个进程把命令行转发给常驻实例后退出。"""

import contextlib
import json
import os

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

# Linux 的 Unix socket 落在 /tmp，多用户终端共用机器时按 uid 隔离
if os.name == "nt":
    KEY = "snapocr.instance.v1"
else:
    KEY = "snapocr.%d.instance.v1" % (os.getuid() if hasattr(os, "getuid") else 0)


class SingleInstance(QObject):
    commandReceived = pyqtSignal(list)

    # try_connect 的三种结果：只有 NO_INSTANCE 才应继续 listen() 成为常驻实例
    FORWARDED = "forwarded"  # 已确认送达（收到 ack）
    NO_INSTANCE = "no-instance"  # 没有其他实例在跑
    UNCERTAIN = "uncertain"  # 连接建立过但未收到 ack：保守视为已转发，避免双开

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._buf = b""

    def try_connect(self, args) -> str:
        """已有实例在跑则转发命令，返回 FORWARDED / NO_INSTANCE / UNCERTAIN。

        「已连接但 ack 超时」不能当作没有实例：此时若本进程再 listen()，
        会 removeServer 掉对方正在用的管道并抢同一名字，表现为偶发双开、热键互抢。
        """
        sock = QLocalSocket()
        sock.connectToServer(KEY)
        if not sock.waitForConnected(600):
            return self.NO_INSTANCE
        try:
            sock.write(json.dumps(args, ensure_ascii=False).encode("utf-8"))
            sock.flush()
            if not sock.waitForBytesWritten(600):
                return self.UNCERTAIN
            # 等服务端 ack，确保其已完整读到命令再断开
            ok = sock.waitForReadyRead(1500)
            resp = bytes(sock.readAll()) if ok else b""
            if resp.strip() == b"ok":
                return self.FORWARDED
            return self.UNCERTAIN
        finally:
            sock.disconnectFromServer()

    def listen(self):
        QLocalServer.removeServer(KEY)  # 清理崩溃残留
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_conn)
        self._server.listen(KEY)

    def _on_conn(self):
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        self._pending = sock
        self._buf = b""  # 累积缓冲：QLocalSocket 不保证一次 readyRead 收完整报文
        # 数据可能随连接一起到达，先试读一次；其余交给 readyRead
        self._try_read()
        with contextlib.suppress(Exception):
            sock.readyRead.connect(self._try_read)
            # 客户端异常断开（超时/被杀/发半截报文后退出）时清理状态：否则 _pending
            # 会指向已死 socket，直到下一次连接才被覆盖（第二轮审计 P2-06）。
            sock.disconnected.connect(self._on_disconnect)

    def _on_disconnect(self):
        """连接断开时释放缓冲状态（主动断开路径已先置 None，不会误清）。"""
        sock = getattr(self, "_pending", None)
        if sock is not None and sock.state() != QLocalSocket.ConnectedState:
            self._pending = None
            self._buf = b""

    def _try_read(self):
        sock = getattr(self, "_pending", None)
        if sock is None:
            return
        chunk = bytes(sock.readAll())
        if not chunk:
            return  # 数据未到齐，等 readyRead 再试
        buf = getattr(self, "_buf", b"") + chunk
        if len(buf) > 64 * 1024:  # 安全上限：命令行转发不可能这么大
            self._pending = None
            self._buf = b""
            with contextlib.suppress(Exception):
                sock.disconnectFromServer()
            return
        # 分片到达时先缓冲，只有完整 JSON 才派发——否则半截报文会被当成空命令，
        # 在应用侧走 "空命令=截屏" 分支，用户没操作却弹出遮罩（探针实证过的缺陷）。
        try:
            args = json.loads(buf.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._buf = buf  # 尚未收全，等下一次 readyRead
            return
        self._buf = b""
        self._pending = None
        with contextlib.suppress(Exception):
            sock.write(b"ok")
            sock.flush()
            sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        self.commandReceived.emit(args if isinstance(args, list) else [])
