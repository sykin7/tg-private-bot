```text
代码空间docker login -u sykin（替换自己的docker名）
输入自己的docker  token
docker build -t sykin/tg-private-bot:v4 .
docker push sykin/tg-private-bot:v4

变量
OWNER_ID=个人ID
BOT_TOKEN=机器人API
CUSTOM_SPAM_KEYWORDS=会员 (随时增减您自己的黑名单)
SPAM_RULES_URL=全世界任何一个广告规则库

端口8080
Command python3
Arguments bot.py
