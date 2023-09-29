import asyncio

from metagpt.roles import Role
from metagpt.schema import Message
from metagpt.logs import logger
from examples.werewolf_game.actions.moderator_actions import (
    InstructSpeak, ParseSpeak, AnnounceGameResult, STEP_INSTRUCTIONS
)
from metagpt.actions import BossRequirement as UserRequirement


class Moderator(Role):
    # 游戏状态属性
    is_game_over = False
    winner = None

    def __init__(
            self,
            name: str = "Moderator",
            profile: str = "Moderator",
            **kwargs,
    ):
        super().__init__(name, profile, **kwargs)
        self._watch([UserRequirement, InstructSpeak, ParseSpeak])
        self._init_actions([InstructSpeak, ParseSpeak, AnnounceGameResult])
        self.step_idx = 0
        self.living_players = ["Player1", "Player2", "Player3", "Player4", "Player5"]
        self.werewolf_players = ["Player1", "Player2"]
        self.good_guys = ["Player3", "Player4", "Player5"]
        self.dead_players = []  # 夜晚阶段，死掉的玩家
        # 假设votes代表白天投票的结果，key是被投票的玩家，value是得票数
        self.votes = {"Player1": 1, "Player2": 2, "Player3": 1, "Player4": 0, "Player5": 0}

    async def _instruct_speak(self):
        step_idx = self.step_idx % len(STEP_INSTRUCTIONS)
        self.step_idx += 1
        return await InstructSpeak().run(step_idx,
                                         living_players=self.living_players,
                                         werewolf_players=self.werewolf_players,
                                         killed_player=self.dead_players,
                                         voted_out_player="Player3")

    async def _parse_speak(self, memories, env):

        self.dead_players, vote_player, parse_info = await ParseSpeak().run(dead_history=self.dead_players,
                                                                            context=memories, env=env)

        # decide to move the game into the next phase
        if not vote_player:
            msg_content, send_to = parse_info[0], self.profile
        # game's termination condition
        elif all(item in self.dead_players for item in self.werewolf_players) or all(
                item in self.dead_players for item in self.good_guys):
            self.is_game_over = True
            msg_content, send_to = parse_info[1], "all"
        else:
            # game's termination condition
            msg_content, send_to = parse_info[2], ""
        return msg_content, send_to

    async def _think(self):

        if self.is_game_over:
            self._rc.todo = AnnounceGameResult()
            return

        # 确定当前是需要InstructSpeak还是ParseSpeak. 通过判断当前流程状态变量，以及消息的cause_by属性
        # 0: InstructSpeak, 1: ParseSpeak,且需要判断消息的cause_by属性
        if self._rc.memory.get()[-1].role in ["User", self.profile]:
            # 1. 上一轮消息是用户指令，解析用户指令，开始游戏
            # 2. 上一轮消息是Moderator自己的指令，继续发出指令，一个事情可以分几条消息来说
            # 3. 上一轮消息是Moderator自己的解析消息，一个阶段结束，发出新一个阶段的指令
            self._rc.todo = InstructSpeak()

        else:
            # 上一轮消息是游戏角色的发言，解析角色的发言
            self._rc.todo = ParseSpeak()

    async def _act(self):
        todo = self._rc.todo
        logger.info(f"{self._setting} ready to {todo}")

        memories = self.get_all_memories()
        print("*" * 10, f"{self._setting}'s current memories: {memories}", "*" * 10)

        # 根据_think的结果，执行InstructSpeak还是ParseSpeak, 并将结果返回
        if isinstance(todo, InstructSpeak):
            msg_content, msg_to_send_to, msg_restriced_to = await self._instruct_speak()
            msg = Message(content=msg_content, role=self.profile, sent_from=self.name,
                          cause_by=InstructSpeak, send_to=msg_to_send_to, restricted_to=msg_restriced_to)

        elif isinstance(todo, ParseSpeak):
            msg_content, send_to = await self._parse_speak(memories, self._rc)
            msg = Message(content=msg_content, role=self.profile, sent_from=self.name, cause_by=ParseSpeak,
                          send_to=send_to)

        elif isinstance(todo, AnnounceGameResult):
            msg_content = await AnnounceGameResult().run(winner=self.winner)
            msg = Message(content=msg_content, role=self.profile, sent_from=self.name, cause_by=AnnounceGameResult)

        logger.info(f"{self._setting}: {msg_content}")

        return msg

    def get_all_memories(self) -> str:
        memories = self._rc.memory.get()
        memories = [str(m) for m in memories]
        memories = "\n".join(memories)
        return memories