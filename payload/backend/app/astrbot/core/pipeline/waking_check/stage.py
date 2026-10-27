from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
from collections.abc import AsyncGenerator, Callable
import re
from astrbot import logger
from astrbot.core.message.components import At, AtAll, Plain, Reply
from astrbot.core.message.message_event_result import MessageChain, MessageEventResult
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import EventType, star_handlers_registry
from ..context import PipelineContext
from ..stage import Stage, register_stage
UNIQUE_SESSION_ID_BUILDERS: dict[str, Callable[[AstrMessageEvent], str | None]] = {'aiocqhttp': lambda e: f'{e.get_sender_id()}_{e.get_group_id()}', 'slack': lambda e: f'{e.get_sender_id()}_{e.get_group_id()}', 'dingtalk': lambda e: e.get_sender_id(), 'qq_official': lambda e: e.get_sender_id(), 'qq_official_webhook': lambda e: e.get_sender_id(), 'lark': lambda e: f'{e.get_sender_id()}%{e.get_group_id()}', 'misskey': lambda e: f'{e.get_session_id()}_{e.get_sender_id()}', 'matrix': lambda e: f'{e.get_sender_id()}_{e.get_group_id() or e.get_session_id()}'}

def build_unique_session_id(event: AstrMessageEvent) -> str | None:
    platform = event.get_platform_name()
    builder = UNIQUE_SESSION_ID_BUILDERS.get(platform)
    return builder(event) if builder else None

@register_stage
class WakingCheckStage(Stage):
    """检查是否需要唤醒。唤醒机器人有如下几点条件：

    1. 机器人被 @ 了
    2. 机器人的消息被提到了
    3. 以 wake_prefix 前缀开头，并且消息没有以 At 消息段开头
    4. 插件（Star）的 handler filter 通过
    5. 私聊情况下，位于 admins_id 列表中的管理员的消息（在白名单阶段中）
    """

    async def initialize(self, ctx: PipelineContext) -> None:
        """初始化唤醒检查阶段

        Args:
            ctx (PipelineContext): 消息管道上下文对象, 包括配置和插件管理器

        """
        self.ctx = ctx
        self.no_permission_reply = self.ctx.astrbot_config['platform_settings'].get('no_permission_reply', True)
        self.friend_message_needs_wake_prefix = self.ctx.astrbot_config['platform_settings'].get('friend_message_needs_wake_prefix', False)
        self.ignore_bot_self_message = self.ctx.astrbot_config['platform_settings'].get('ignore_bot_self_message', False)
        self.ignore_at_all = self.ctx.astrbot_config['platform_settings'].get('ignore_at_all', False)
        self.disable_builtin_commands = self.ctx.astrbot_config.get('disable_builtin_commands', False)
        platform_settings = self.ctx.astrbot_config.get('platform_settings', {})
        self.unique_session = platform_settings.get('unique_session', False)

    async def process(self, event: AstrMessageEvent) -> None | AsyncGenerator[None, None]:
        if self.unique_session and event.message_obj.type == MessageType.GROUP_MESSAGE:
            sid = build_unique_session_id(event)
            if sid:
                event.session_id = sid
        if self.ignore_bot_self_message and event.get_self_id() == event.get_sender_id():
            event.stop_event()
            return
        command_text = ''.join((part.text for part in event.get_messages() if isinstance(part, Plain))).strip() or (event.message_str or '').strip()
        if (command_text.startswith(('/', '／', '#', '＃')) or re.match('^(?:电脑|控制电脑|本地agent|agent\\b|截图|截屏|打开|启动)', command_text, re.I)) and str(event.get_sender_id()) not in _portable_owners(as_int=False):
            event.stop_event()
            await event.send(MessageChain().message('拒绝执行：只有主人可以使用命令。'))
            return
        event.message_str = event.message_str.strip()
        api_key_allow_admin_role = event.get_extra('_api_key_allow_admin_role')
        for admin_id in self.ctx.astrbot_config['admins_id']:
            if api_key_allow_admin_role is not False and str(event.get_sender_id()) == admin_id:
                event.role = 'admin'
                break
        wake_prefixes = self.ctx.astrbot_config['wake_prefix']
        messages = event.get_messages()
        is_wake = False
        for wake_prefix in wake_prefixes:
            if event.message_str.startswith(wake_prefix):
                if not event.is_private_chat() and isinstance(messages[0], At) and (str(messages[0].qq) != str(event.get_self_id())) and (str(messages[0].qq) != 'all'):
                    break
                is_wake = True
                event.is_at_or_wake_command = True
                event.is_wake = True
                event.message_str = event.message_str[len(wake_prefix):].strip()
                break
        if not is_wake:
            for message in messages:
                if isinstance(message, At) and str(message.qq) == str(event.get_self_id()) or (isinstance(message, AtAll) and (not self.ignore_at_all)) or (isinstance(message, Reply) and str(message.sender_id) == str(event.get_self_id())):
                    is_wake = True
                    event.is_wake = True
                    wake_prefix = ''
                    event.is_at_or_wake_command = True
                    break
            if event.is_private_chat() and (not self.friend_message_needs_wake_prefix or event.get_platform_name() == 'webchat'):
                is_wake = True
                event.is_wake = True
                event.is_at_or_wake_command = True
                wake_prefix = ''
        activated_handlers = []
        handlers_parsed_params = {}
        enabled_plugins_name = self.ctx.astrbot_config.get('plugin_set', ['*'])
        if enabled_plugins_name == ['*']:
            event.plugins_name = None
        else:
            event.plugins_name = enabled_plugins_name
        logger.debug(f'enabled_plugins_name: {enabled_plugins_name}')
        for handler in star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent, plugins_name=event.plugins_name):
            if self.disable_builtin_commands and handler.handler_module_path == 'astrbot.builtin_stars.builtin_commands.main':
                continue
            passed = True
            permission_not_pass = False
            permission_filter_raise_error = False
            if len(handler.event_filters) == 0:
                continue
            for filter in handler.event_filters:
                try:
                    if isinstance(filter, PermissionTypeFilter):
                        if not filter.filter(event, self.ctx.astrbot_config):
                            permission_not_pass = True
                            permission_filter_raise_error = filter.raise_error
                    elif not filter.filter(event, self.ctx.astrbot_config):
                        passed = False
                        break
                except Exception as e:
                    await event.send(MessageEventResult().message(f'插件 {star_map[handler.handler_module_path].name}: {e}').use_markdown(False))
                    event.stop_event()
                    passed = False
                    break
            if passed:
                if str(event.get_sender_id()) not in _portable_owners(as_int=False) and any((isinstance(f, (CommandFilter, CommandGroupFilter)) for f in handler.event_filters)):
                    event.stop_event()
                    await event.send(MessageChain().message('拒绝执行：只有主人可以使用命令。'))
                    return
                if permission_not_pass:
                    if not permission_filter_raise_error:
                        continue
                    if self.no_permission_reply:
                        await event.send(MessageChain().message(f'您(ID: {event.get_sender_id()})的权限不足以使用此指令。通过 /sid 获取 ID 并请管理员添加。'))
                    logger.info(f'User ID {event.get_sender_id()} lacks permission to trigger {star_map[handler.handler_module_path].name}.')
                    event.stop_event()
                    return
                is_wake = True
                event.is_wake = True
                is_group_cmd_handler = any((isinstance(f, CommandGroupFilter) for f in handler.event_filters))
                if not is_group_cmd_handler:
                    activated_handlers.append(handler)
                    if 'parsed_params' in event.get_extra(default={}):
                        handlers_parsed_params[handler.handler_full_name] = event.get_extra('parsed_params')
            event._extras.pop('parsed_params', None)
        activated_handlers = await SessionPluginManager.filter_handlers_by_session(event, activated_handlers)
        event.set_extra('activated_handlers', activated_handlers)
        event.set_extra('handlers_parsed_params', handlers_parsed_params)
        if not is_wake:
            event.stop_event()
