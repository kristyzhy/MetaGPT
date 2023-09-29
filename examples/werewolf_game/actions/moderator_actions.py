import asyncio
import collections
from random import random

from metagpt.actions import Action

STEP_INSTRUCTIONS = {
    # 上帝需要介入的全部步骤和对应指令
    # The 1-st night
    0: {"content": "It’s dark, everyone close your eyes. I will talk with you/your team secretly at night.",
        "send_to": "Moderator",  # for moderator to continuen speaking
        "restricted_to": ""},
    1: {"content": "Guard, please open your eyes!",
        "send_to": "Moderator",  # for moderator to continuen speaking
        "restricted_to": ""},
    2: {"content": """Guard, now tell me who you protect tonight? 
                You only choose one from the following living options please: {living_players}. Or you can pass. For example: I protect ...""",
        "send_to": "Guard",
        "restricted_to": "Guard"},
    3: {"content": "Guard, close your eyes",
        "send_to": "Moderator",
        "restricted_to": ""},
    4: {"content": "Werewolves, please open your eyes!",
        "send_to": "Moderator",
        "restricted_to": ""},
    5: {"content": """Werewolves, I secretly tell you that {werewolf_players} are
                   all of the 2 werewolves! Keep in mind you are teammates. The rest players are not werewolves.
                   choose one from the following living options please:
                   {living_players}. For example: I kill ...""",
        "send_to": "Werewolf",
        "restricted_to": "Werewolf"},
    6: {"content": "Werewolves, close your eyes",
        "send_to": "Moderator",
        "restricted_to": ""},
    7: {"content": "Witch, please open your eyes!",
        "send_to": "Moderator",
        "restricted_to": ""},
    8: {"content": """Witch, tonight {killed_player} has been killed by the werewolves. 
                    You have a bottle of antidote, would you like to save him/her? If not, simply Pass.""",
        "send_to": "Witch",
        "restricted_to": "Witch"},  # 要先判断女巫是否有解药，再去询问女巫是否使用解药救人
    9: {"content": """Witch, you also have a bottle of poison, would you like to use it to kill one of the living players? 
                    Choose one from the following living options: {living_players}. If not, simply Pass.""",
        "send_to": "Witch",
        "restricted_to": "Witch"},  #
    10: {"content": "Witch, close your eyes",
         "send_to": "Moderator",
         "restricted_to": ""},
    11: {"content": "Seer, please open your eyes!",
         "send_to": "Moderator",
         "restricted_to": ""},
    12: {"content": """Seer, you can check one player's identity. Who are you going to verify its identity tonight? 
                  Choose only one from the following living options:{living_players}.""",
         "send_to": "Seer",
         "restricted_to": "Seer"},
    13: {"content": "Seer, close your eyes",
         "send_to": "Moderator",
         "restricted_to": ""},
    # The 1-st daytime
    14: {"content": """It's daytime. Everyone woke up except those who had been killed.""",
         "send_to": "Moderator",
         "restricted_to": ""},
    15: {"content": "{killed_player} was killed last night. Or, it was a peaceful night and no one died!",
         "send_to": "Moderator",
         "restricted_to": ""},
    16: {"content": """Now freely talk about roles of other players with each other based on your observation and 
                    reflection with few sentences. Decide whether to reveal your identity based on your reflection.""",
         "send_to": "",  # send to all to speak in daytime
         "restricted_to": ""},
    17: {"content": """Now vote and tell me who you think is the werewolf. Don’t mention your role.
                    You only choose one from the following living options please:
                    {living_players}. Or you can pass. For example: I vote to kill ...""",
         "send_to": "",
         "restricted_to": ""},
    18: {"content": """{voted_out_player} was eliminated.""",
         "send_to": "Moderator",
         "restricted_to": ""},
}

ROLE_STATES = {
    # 存活状态
    0: "Alive",  # 开场
    1: "Dead",  # 结束
    2: "Protected",  # 被保护
    3: "Poisoned",  # 被毒
    4: "Saved",  # 被救
    5: "Killed"  # 被刀
}

VOTE_PROMPT = """
    Welcome to the daytime discussion phase in the Werewolf game.

    During the day, players discuss and share information about who they suspect might be a werewolf.
    Players can also cast their votes to eliminate a player they believe is a werewolf.

    Here are the conversations from the daytime:

    {vote_message}

    Now it's time to cast your votes.

    You can vote for a player by typing their name.
    Example: "Vote for Player2"

    Here are the voting options:
"""

PARSE_INSTRUCTIONS = {
    0: "Now it's time to vote",
    1: "The {winner} have won! They successfully eliminated all the {loser}."
       "The game has ended. Thank you for playing Werewolf!",
    2: "The night has ended, and it's time to reveal the casualties."
       "During the night, the Werewolves made their move. Unfortunately, they targeted {PlayerName}, who is now dead."
}


class InstructSpeak(Action):
    def __init__(self, name="InstructSpeak", context=None, llm=None):
        super().__init__(name, context, llm)

    async def run(self, step_idx, living_players, werewolf_players, killed_player, voted_out_player):
        instruction_info = STEP_INSTRUCTIONS.get(step_idx, {
            "content": "Unknown instruction.",
            "send_to": "",
            "restricted_to": ""
        })
        content = instruction_info["content"]
        if "{living_players}" in content and "{werewolf_players}" in content:
            content = content.format(living_players=",".join(living_players),
                                     werewolf_players=",".join(werewolf_players))
        if "{living_players}" in content:
            content = content.format(living_players=",".join(living_players))
        if "{werewolf_players}" in content:
            content = content.format(werewolf_players=",".join(werewolf_players))
        if "{killed_player}" in content:
            content = content.format(killed_player=killed_player)
        if "{voted_out_player}" in content:
            content = content.format(voted_out_player=voted_out_player)

        return content, instruction_info["send_to"], instruction_info["restricted_to"]


class ParseSpeak(Action):
    def __init__(self, name="ParseSpeak", context=None, llm=None):
        super().__init__(name, context, llm)
        self.daytime_info = collections.defaultdict(list)
        self.night_info = collections.defaultdict(list)
        self.vote_message = []

    async def run(self, dead_history, context, env):

        for m in env.memory.get():
            role = m.sent_from if hasattr(m, 'sent_from') else ""
            content = m.content if hasattr(m, 'content') else ""
            target = m.sent_to if hasattr(m, 'sent_to') else ""
            restricted = m.restricted_to if hasattr(m, 'restricted_to') else ""
            if target == 'all':
                self.daytime_info[role] = [content, target, restricted]
            else:
                self.night_info[role] = [content, target, restricted]

        # collect info from the night and identify the dead player
        for role in self.night_info:
            if "kill" in self.night_info[role][0] and self.night_info[role][1]:
                target = self.night_info[role][1]
                print("env.get_roles[target]", env, env.env.roles)
                env.env.roles[target].set_status(ROLE_STATES[5])
        for role in self.night_info:
            if ("save" or "guard") in self.night_info[role][0]:
                save_target = self.night_info[role][1]
                if save_target == target:
                    env.env.roles[target].set_status(ROLE_STATES[0])
                else:
                    dead_history.append(target)

        # collect message from the daytime and identify the vote player
        for role in self.daytime_info:
            self.vote_message += f"\n{self.daytime_info[role][0]}"

        vote_player = await self.llm.aask(VOTE_PROMPT.format(vote_message=self.vote_message))
        dead_history.append(vote_player)

        return dead_history, vote_player, PARSE_INSTRUCTIONS


class SummarizeNight(Action):
    """consider all events at night, conclude which player dies (can be a peaceful night)"""

    def __init__(self, name="SummarizeNight", context=None, llm=None):
        super().__init__(name, context, llm)

    async def run(self, events):
        # 假设events是一个字典，代表夜晚发生的多个事件，key是事件类型，value是该事件对应的玩家
        # 例如被狼人杀的玩家：{"killed_by_werewolves": "Player1"}
        # 被守卫守护的玩家：{"protected_by_guard": "Player2"}
        # 被女巫救的玩家：{"saved_by_witch": "Player3"}
        # 被女巫毒的玩家：{"poisoned_by_witch": "Player4"}
        # 被预言家查验的玩家：{"verified_by_seer": "Player5"}
        # 若没有事件发生，则events为空字典
        killed_by_werewolves = events.get("killed_by_werewolves", "")
        protected_by_guard = events.get("protected_by_guard", "")
        saved_by_witch = events.get("saved_by_witch", "")
        poisoned_by_witch = events.get("poisoned_by_witch", "")

        # 若狼人杀的人和守卫守的人是同一个人，那么该人就会活着；
        if protected_by_guard and killed_by_werewolves and protected_by_guard == killed_by_werewolves:
            return "It was a peaceful night. No one was killed."

        # 若守卫和女巫都救了同一个人，那么该人就会死
        if protected_by_guard and saved_by_witch and protected_by_guard == saved_by_witch:
            return f"{protected_by_guard} was killed by the werewolves."

        if saved_by_witch:
            return f"{saved_by_witch} was saved by the witch."

        if poisoned_by_witch:
            return f"{poisoned_by_witch} was poisoned by the witch."

        if killed_by_werewolves:
            return f"{killed_by_werewolves} was killed by the werewolves."


class SummarizeDay(Action):
    """consider all votes at day, conclude which player dies"""

    def __init__(self, name="SummarizeDay", context=None, llm=None):
        super().__init__(name, context, llm)

    async def run(self, votes):
        # 假设votes是一个字典，代表白天投票的结果，key是被投票的玩家，value是得票数
        # 例如：{"Player1": 2, "Player2": 1, "Player3": 1, "Player4": 0}
        # 表示Player1得到2票，Player2和Player3各得到1票，Player4得到0票
        # 若平票，则随机选一个人出局
        if not votes:
            return "No votes were cast. No one was killed."

        max_votes = max(votes.values())
        players_with_max_votes = [player for player, vote_count in votes.items() if vote_count == max_votes]

        if len(players_with_max_votes) == 1:
            eliminated_player = players_with_max_votes[0]
            return f"{eliminated_player} was voted out and eliminated."
        else:
            # 若平票，则随机选一个人出局
            eliminated_player = players_with_max_votes[int(random() * len(players_with_max_votes))]
            return f"There was a tie in the votes. {eliminated_player} was randomly chosen and eliminated."


class AnnounceGameResult(Action):

    async def run(self, winner: str):
        return f"Game over! The winner is {winner}"


async def main():
    rst1 = await SummarizeDay().run({"Player1": 0, "Player2": 0, "Player3": 0, "Player4": 0})
    rst2 = await SummarizeNight().run({"killed_by_werewolves": "Player1"})
    # 表示第2个步骤的指令，living_players是所有活着的玩家，werewolf_players是所有狼人，killed_player是被杀的玩家，voted_out_player是被投票出局的玩家
    rst3 = await InstructSpeak().run(2, ["Player1", "Player2", "Player3", "Player4"],
                                     ["Player3", "Player4"], "Player4", "Player3")
    print(rst1)
    print(rst2)
    print(rst3)


if __name__ == '__main__':
    asyncio.run(main())