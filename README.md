```text
代码空间docker login -u sykin（替换自己的docker名）
输入自己的docker  token
docker build -t sykin/tg-private-bot:v4 .
docker push sykin/tg-private-bot:v4
变量添加OWNER_ID个人ID，BOT_TOKEN机器人API
