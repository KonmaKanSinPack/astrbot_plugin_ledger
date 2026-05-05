# astrbot_plugin_ledger

一个用于 AstrBot 的模拟记账插件。

这个插件不会自动推断收入或支出，所有账目都只能通过手动命令，或者由 AI 在用户明确要求后调用对应 Tool 来修改。现在整个插件共享一份全局账本，数据使用 AstrBot 插件 KV 存储保存。

手动修改全局账本时会检查白名单，只有 `allowed_ids` 中配置的 sender_id 才能执行修改类命令；LLM Tool 默认仍可修改账本。

## 功能

- 手动增加收入
- 手动增加支出
- 直接改写累计收入
- 直接改写累计支出
- 查看当前汇总和最近记录
- 清空全局账本
- 暴露给 AI 的记账 Tool

## 配置

插件提供一个配置项：

- `allowed_ids`: 可以手动修改全局账本的 sender_id 白名单，默认是空列表

示例：

```json
{
	"allowed_ids": ["123456", "987654"]
}
```

当白名单为空时，手动命令不能修改账本，只有 LLM Tool 可以修改。

## 指令

```text
/ledger help
/ledger show
/ledger income 1000 工资
/ledger expense 35.5 午饭
/ledger set_income 5000
/ledger set_expense 1200
/ledger reset
```

## AI Tools

插件注册了以下 Tool，可供 AstrBot Agent 在合适时机调用：

- `ledger_show_summary`
- `ledger_add_income`
- `ledger_add_expense`
- `ledger_set_income_total`
- `ledger_set_expense_total`

这些 Tool 的设计原则是“只在用户明确要求修改账本时调用”，不会自动替用户生成收入或支出；它们修改的是同一份全局账本。

## 兼容性

- AstrBot `>= 4.9.2`

## 参考

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件存储文档](https://docs.astrbot.app/dev/star/guides/storage.html)
