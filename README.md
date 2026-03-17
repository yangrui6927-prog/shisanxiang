# 中国移动招标信息推送系统

自动抓取中国移动采购与招标网(b2b.10086.cn)的招标信息，根据用户订阅的关键词进行匹配，并通过飞书Webhook推送到指定群聊。

## 核心功能

- **自动抓取**：使用Playwright处理动态网页，抓取最近25小时内的公告
- **智能匹配**：根据销售人员的关注关键词精准匹配招标信息
- **去重推送**：使用详情URL作为唯一标识，避免重复推送
- **多群支持**：支持不同用户推送到不同的飞书群
- **类型识别**：自动识别公告类型（招标公告、中标公示、候选人公示等）

## 文件结构

```
bidding-notifier/
├── bidding_notifier.py       # 主程序
├── requirements.txt          # Python依赖
├── 招标订阅表.csv            # 订阅配置
├── README.md                 # 项目说明
└── .github/
    └── workflows/
        └── bidding-monitor.yml  # GitHub Actions配置
```

## 快速开始

### 1. 配置环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `FEISHU_WEBHOOK` | 默认飞书Webhook地址 | 是 |
| `FETCH_HOURS` | 抓取时间范围（小时） | 否，默认25 |
| `LOCAL_CSV_FILE` | 订阅表文件路径 | 否，默认"招标订阅表.csv" |

### 2. 配置订阅表

编辑 `招标订阅表.csv`：

```csv
销售姓名,Open ID,关注关键词,Webhook
张三,ou_xxx,咪咕公司|北京|上海,https://open.feishu.cn/open-apis/bot/v2/hook/xxx
李四,ou_yyy,物联网公司|广东|深圳,https://open.feishu.cn/open-apis/bot/v2/hook/yyy
```

- **销售姓名**：用户名称
- **Open ID**：飞书用户ID
- **关注关键词**：多个关键词用 `|` 分隔
- **Webhook**：可选，指定该用户匹配的招标推送到哪个群（为空使用默认）

### 3. 本地运行测试

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 设置环境变量并运行
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
python bidding_notifier.py
```

## 部署到 GitHub Actions

### 1. 创建私有仓库

1. 登录 GitHub
2. 创建 **Private** 仓库（保护敏感信息）
3. 仓库名称：`bidding-notifier`

### 2. 上传代码

将以下文件上传到仓库根目录：
- `bidding_notifier.py`
- `requirements.txt`
- `招标订阅表.csv`
- `.github/workflows/bidding-monitor.yml`

### 3. 配置 GitHub Secrets

进入仓库 → `Settings` → `Secrets and variables` → `Actions`，添加：

| Secret名称 | 值 |
|------------|-----|
| `FEISHU_WEBHOOK` | 你的飞书Webhook地址 |

### 4. 获取飞书Webhook

1. 进入目标飞书群聊
2. 点击群设置 → `群机器人` → `添加机器人`
3. 选择 `自定义机器人`
4. 复制 Webhook 地址

### 5. 测试运行

1. 进入仓库 → `Actions` 标签页
2. 点击 `招标信息监控` 工作流
3. 点击 `Run workflow` 手动触发

## 定时配置

默认每小时运行一次（北京时间每小时的第8分钟）：

```yaml
- cron: '0 * * * *'
```

**时间对应关系：**
- UTC 0:00 = 北京时间 8:00
- UTC 1:00 = 北京时间 9:00

**常用配置：**
- `'0 0-14 * * *'` - 北京时间 8:00-22:00 每小时运行
- `'0 */2 * * *'` - 每2小时运行一次
- `'0 0,6,12,18 * * *'` - 每6小时运行一次

## 公告类型映射

系统根据URL参数自动识别公告类型：

| publishType | 中文类型 |
|-------------|----------|
| CANDIDATE_PUBLICITY | 中标候选人公示 |
| WIN_BID / WIN_BID_PUBLICITY | 中标公告/中标结果公示 |
| BIDDING | 招标公告 |
| BIDDING_PROCUREMENT | 招标采购公告 |
| PROCUREMENT | 直接采购公告 |
| SINGLE_SOURCE | 单一来源公示 |
| PREQUALIFICATION | 资格预审公告 |
| CORRECTION | 更正公告 |
| TERMINATION | 终止公告 |
| SUSPENSION | 暂停公告 |
| CLARIFICATION | 澄清公告 |

## 推送消息格式

```
您好，此次一共检索5条新消息（招标公告2条 | 中标候选人公示3条）～

【招标公告1】
发布单位：咪咕公司
发布时间：2025-03-09 10:30:00
《XX系统建设项目招标公告》
链接：https://b2b.10086.cn/#/noticeDetail?...

【中标候选人公示1】
...
```

## 常见问题

### 1. 重复推送问题

GitHub Actions 每次运行都是新环境，推送记录通过 Artifacts 持久化。工作流已配置自动保存和恢复 `pushed_bids.json`。

### 2. 抓取超时

如果网页加载慢，可以修改脚本中的等待时间：
```python
self.page.wait_for_timeout(10000)  # 改为 15000 或更长
```

### 3. 匹配不到招标

- 检查关键词是否正确（区分大小写）
- 检查CSV编码是否为UTF-8
- 检查 `FETCH_HOURS` 是否设置过短

### 4. 推送失败

- 检查Webhook地址是否正确
- 检查飞书群机器人是否被删除
- 检查网络是否能访问飞书API

## 依赖安装

```bash
pip install requests playwright python-dateutil
playwright install chromium
```

## 注意事项

1. **隐私保护**：Webhook地址应存储在环境变量或GitHub Secrets中
2. **合规性**：抓取频率不要过高，避免对目标网站造成压力
3. **时区**：系统统一使用北京时间（UTC+8）

## License

MIT
