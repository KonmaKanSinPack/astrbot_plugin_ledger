from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

LEDGER_PREFIX = "ledger"
MAX_RECORDS = 20
MONEY_PRECISION = Decimal("0.01")


@register(
    "astrbot_plugin_ledger",
    "saier",
    "全局模拟记账插件，收入和支出仅能通过手动命令或 AI Tool 修改",
    "1.0.0",
)
class LedgerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config if config is not None else {}

    def _allowed_ids(self) -> set[str]:
        if not isinstance(self.config, dict):
            return set()

        raw_allowed_ids = self.config.get("allowed_ids", [])
        if not isinstance(raw_allowed_ids, list):
            return set()

        allowed_ids: set[str] = set()
        for raw_allowed_id in raw_allowed_ids:
            allowed_id = str(raw_allowed_id).strip()
            if allowed_id:
                allowed_ids.add(allowed_id)
        return allowed_ids

    def _command_modify_denied_message(self, event: AstrMessageEvent) -> str | None:
        sender_id = str(event.get_sender_id() or "").strip()
        allowed_ids = self._allowed_ids()
        if sender_id and sender_id in allowed_ids:
            return None

        sender_label = sender_id or "未知"
        if allowed_ids:
            return (
                f"你没有权限修改全局账本。当前发送者 ID: {sender_label}。"
                "请在插件配置 allowed_ids 白名单中加入该 ID。"
            )

        return (
            f"你没有权限修改全局账本。当前发送者 ID: {sender_label}。"
            "插件还没有配置任何 allowed_ids 白名单。"
        )

    def _ledger_key(self, event: AstrMessageEvent) -> str:
        del event
        return f"{LEDGER_PREFIX}:global"

    def _default_ledger(self) -> dict[str, Any]:
        return {
            "income": self._format_amount(Decimal("0")),
            "expense": self._format_amount(Decimal("0")),
            "records": [],
        }

    def _format_amount(self, amount: Decimal) -> str:
        return f"{amount.quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP):f}"

    def _parse_amount(self, raw_amount: Any, *, allow_zero: bool) -> Decimal:
        try:
            amount = Decimal(str(raw_amount)).quantize(
                MONEY_PRECISION,
                rounding=ROUND_HALF_UP,
            )
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("金额格式不正确，请输入数字，例如 88.50") from exc

        if amount < 0:
            raise ValueError("金额不能小于 0")
        if not allow_zero and amount == Decimal("0"):
            raise ValueError("金额必须大于 0")
        return amount

    def _safe_amount(self, raw_amount: Any) -> str:
        try:
            return self._format_amount(self._parse_amount(raw_amount, allow_zero=True))
        except ValueError:
            return self._format_amount(Decimal("0"))

    async def _load_ledger(self, event: AstrMessageEvent) -> dict[str, Any]:
        ledger = await self.get_kv_data(self._ledger_key(event), None)
        if not isinstance(ledger, dict):
            return self._default_ledger()

        records = ledger.get("records", [])
        normalized_records: list[dict[str, str]] = []
        if isinstance(records, list):
            for record in records[-MAX_RECORDS:]:
                if not isinstance(record, dict):
                    continue
                record_type = str(record.get("type", "")).strip()
                if record_type not in {"income", "expense"}:
                    continue
                action = str(record.get("action", "add")).strip() or "add"
                timestamp = str(record.get("timestamp", "")).strip()
                note = str(record.get("note", "")).strip()
                amount = self._safe_amount(record.get("amount", "0"))

                normalized_records.append(
                    {
                        "type": record_type,
                        "action": action,
                        "timestamp": timestamp,
                        "operator": str(record.get("operator", "")).strip(),
                        "note": note,
                        "amount": amount,
                    }
                )

        return {
            "income": self._safe_amount(ledger.get("income", "0")),
            "expense": self._safe_amount(ledger.get("expense", "0")),
            "records": normalized_records,
        }

    async def _save_ledger(self, event: AstrMessageEvent, ledger: dict[str, Any]) -> None:
        await self.put_kv_data(self._ledger_key(event), ledger)

    def _extract_note(
        self,
        event: AstrMessageEvent,
        command_name: str,
        fallback: str = "",
    ) -> str:
        if fallback.strip():
            return fallback.strip()

        message = (event.message_str or "").strip()
        if not message:
            return ""

        tokens = message.split()
        if tokens and tokens[0].lstrip("/") == "ledger":
            tokens = tokens[1:]
        if tokens and tokens[0] == command_name:
            tokens = tokens[1:]
        if tokens:
            tokens = tokens[1:]
        return " ".join(tokens).strip()

    def _append_record(
        self,
        event: AstrMessageEvent,
        ledger: dict[str, Any],
        *,
        record_type: str,
        action: str,
        amount: Decimal,
        note: str,
        operator: str | None = None,
    ) -> None:
        records = ledger.setdefault("records", [])
        if not isinstance(records, list):
            records = []

        records.append(
            {
                "type": record_type,
                "action": action,
                "amount": self._format_amount(amount),
                "operator": operator or event.get_sender_name() or event.get_sender_id() or "未知用户",
                "note": note.strip(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        ledger["records"] = records[-MAX_RECORDS:]

    def _summary_text(self, event: AstrMessageEvent, ledger: dict[str, Any]) -> str:
        income = Decimal(ledger["income"])
        expense = Decimal(ledger["expense"])
        balance = income - expense
        del event

        lines = [
            "账本归属：全局账本",
            f"总收入：{self._format_amount(income)}",
            f"总支出：{self._format_amount(expense)}",
            f"结余：{self._format_amount(balance)}",
        ]

        records = ledger.get("records", [])
        if records:
            lines.append("")
            lines.append("最近记录：")
            for record in reversed(records[-5:]):
                label = "收入" if record["type"] == "income" else "支出"
                action = "累计" if record.get("action") == "add" else "改为"
                operator = f" | 操作人：{record['operator']}" if record.get("operator") else ""
                note = f" | {record['note']}" if record.get("note") else ""
                lines.append(
                    f"{record['timestamp']} | {label}{action} {record['amount']}{operator}{note}"
                )
        else:
            lines.append("")
            lines.append("最近记录：暂无")

        return "\n".join(lines)

    async def _change_total(
        self,
        event: AstrMessageEvent,
        *,
        record_type: str,
        raw_amount: Any,
        note: str = "",
        action: str = "add",
        allow_llm: bool = False,
        operator: str | None = None,
    ) -> str:
        if not allow_llm:
            denied_message = self._command_modify_denied_message(event)
            if denied_message:
                return denied_message

        allow_zero = action == "set"
        amount = self._parse_amount(raw_amount, allow_zero=allow_zero)
        ledger = await self._load_ledger(event)
        field = "income" if record_type == "income" else "expense"
        current_total = Decimal(ledger[field])

        if action == "set":
            new_total = amount
        else:
            new_total = current_total + amount

        ledger[field] = self._format_amount(new_total)
        self._append_record(
            event,
            ledger,
            record_type=record_type,
            action=action,
            amount=amount,
            note=note,
            operator=operator,
        )
        await self._save_ledger(event, ledger)

        type_label = "收入" if record_type == "income" else "支出"
        amount_text = self._format_amount(amount)
        if action == "set":
            headline = f"已将{type_label}累计值改为 {amount_text}"
        else:
            headline = f"已记录一笔{type_label} {amount_text}"

        if note:
            headline = f"{headline}（备注：{note}）"

        return f"{headline}\n\n{self._summary_text(event, ledger)}"

    async def _show_summary(self, event: AstrMessageEvent) -> str:
        ledger = await self._load_ledger(event)
        return self._summary_text(event, ledger)

    @filter.command_group("ledger")
    def ledger(self):
        """模拟记账命令组。"""

    @ledger.command("help")
    async def ledger_help(self, event: AstrMessageEvent):
        """显示模拟记账插件帮助。"""
        help_text = "\n".join(
            [
                "模拟记账插件指令：",
                "/ledger show - 查看当前账本汇总和最近记录",
                "/ledger income 金额 [备注] - 手动增加一笔收入",
                "/ledger expense 金额 [备注] - 手动增加一笔支出",
                "/ledger set_income 金额 - 直接改写累计收入",
                "/ledger set_expense 金额 - 直接改写累计支出",
                "/ledger reset - 清空全局账本",
                "",
                "说明：本插件不会自动推断收入或支出，只有手动命令或 AI Tool 才会改动全局账本。",
                "说明：手动修改命令仅 allowed_ids 白名单内的 sender_id 可执行。",
            ]
        )
        yield event.plain_result(help_text)

    @ledger.command("show")
    async def ledger_show(self, event: AstrMessageEvent):
        """查看全局账本汇总。"""
        yield event.plain_result(await self._show_summary(event))

    @ledger.command("income")
    async def ledger_income(
        self,
        event: AstrMessageEvent,
        amount: str,
        note: str = "",
    ):
        """手动增加收入。"""
        try:
            message = await self._change_total(
                event,
                record_type="income",
                raw_amount=amount,
                note=self._extract_note(event, "income", note),
                action="add",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"记录收入失败: {exc}")
            message = "记录收入失败，请检查日志。"
        yield event.plain_result(message)

    @ledger.command("expense")
    async def ledger_expense(
        self,
        event: AstrMessageEvent,
        amount: str,
        note: str = "",
    ):
        """手动增加支出。"""
        try:
            message = await self._change_total(
                event,
                record_type="expense",
                raw_amount=amount,
                note=self._extract_note(event, "expense", note),
                action="add",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"记录支出失败: {exc}")
            message = "记录支出失败，请检查日志。"
        yield event.plain_result(message)

    @ledger.command("set_income")
    async def ledger_set_income(self, event: AstrMessageEvent, amount: str):
        """手动改写累计收入。"""
        try:
            message = await self._change_total(
                event,
                record_type="income",
                raw_amount=amount,
                action="set",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"设置累计收入失败: {exc}")
            message = "设置累计收入失败，请检查日志。"
        yield event.plain_result(message)

    @ledger.command("set_expense")
    async def ledger_set_expense(self, event: AstrMessageEvent, amount: str):
        """手动改写累计支出。"""
        try:
            message = await self._change_total(
                event,
                record_type="expense",
                raw_amount=amount,
                action="set",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"设置累计支出失败: {exc}")
            message = "设置累计支出失败，请检查日志。"
        yield event.plain_result(message)

    @ledger.command("reset")
    async def ledger_reset(self, event: AstrMessageEvent):
        """清空全局账本。"""
        denied_message = self._command_modify_denied_message(event)
        if denied_message:
            yield event.plain_result(denied_message)
            return

        try:
            await self.delete_kv_data(self._ledger_key(event))
            message = "全局模拟账本已清空。"
        except Exception as exc:
            logger.error(f"清空账本失败: {exc}")
            message = "清空账本失败，请检查日志。"
        yield event.plain_result(message)

    @filter.llm_tool("ledger_show_summary")
    async def ledger_show_summary_tool(self, event: AstrMessageEvent):
        """Read the shared global ledger summary before or after a bookkeeping change."""
        yield event.plain_result(await self._show_summary(event))

    @filter.llm_tool("ledger_add_income")
    async def ledger_add_income_tool(
        self,
        event: AstrMessageEvent,
        amount: str,
        note: str = "",
    ):
        """Record manual income for the shared global ledger.

        Use this tool only when the user explicitly asks to add income.
        """
        try:
            message = await self._change_total(
                event,
                record_type="income",
                raw_amount=amount,
                note=note.strip(),
                action="add",
                allow_llm=True,
                operator=f"LLM({event.get_sender_name() or event.get_sender_id() or '未知用户'})",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"AI 调用收入工具失败: {exc}")
            message = "记录收入失败，请检查日志。"
        yield event.plain_result(message)

    @filter.llm_tool("ledger_add_expense")
    async def ledger_add_expense_tool(
        self,
        event: AstrMessageEvent,
        amount: str,
        note: str = "",
    ):
        """Record manual expense for the shared global ledger.

        Use this tool only when the user explicitly asks to add expense.
        """
        try:
            message = await self._change_total(
                event,
                record_type="expense",
                raw_amount=amount,
                note=note.strip(),
                action="add",
                allow_llm=True,
                operator=f"LLM({event.get_sender_name() or event.get_sender_id() or '未知用户'})",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"AI 调用支出工具失败: {exc}")
            message = "记录支出失败，请检查日志。"
        yield event.plain_result(message)

    @filter.llm_tool("ledger_set_income_total")
    async def ledger_set_income_total_tool(
        self,
        event: AstrMessageEvent,
        amount: str,
    ):
        """Set the shared global ledger total income to a specific value.

        Use this tool only when the user explicitly wants to overwrite total income.
        """
        try:
            message = await self._change_total(
                event,
                record_type="income",
                raw_amount=amount,
                action="set",
                allow_llm=True,
                operator=f"LLM({event.get_sender_name() or event.get_sender_id() or '未知用户'})",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"AI 设置累计收入失败: {exc}")
            message = "设置累计收入失败，请检查日志。"
        yield event.plain_result(message)

    @filter.llm_tool("ledger_set_expense_total")
    async def ledger_set_expense_total_tool(
        self,
        event: AstrMessageEvent,
        amount: str,
    ):
        """Set the shared global ledger total expense to a specific value.

        Use this tool only when the user explicitly wants to overwrite total expense.
        """
        try:
            message = await self._change_total(
                event,
                record_type="expense",
                raw_amount=amount,
                action="set",
                allow_llm=True,
                operator=f"LLM({event.get_sender_name() or event.get_sender_id() or '未知用户'})",
            )
        except ValueError as exc:
            message = str(exc)
        except Exception as exc:
            logger.error(f"AI 设置累计支出失败: {exc}")
            message = "设置累计支出失败，请检查日志。"
        yield event.plain_result(message)
