# 物品最新均价代理（Node/Express）

这是一个最小但更适合实战调试和直接部署的项目，用来把“物品最新平均价格（指定ID）”接口包装成你自己可调用的 API。

## 一、基础运行

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

复制一份示例配置：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少填这几个：

```env
OPENID=你自己的值
ACCESS_TOKEN=你自己的值
ACCTYPE=qc
APPID=101491592
```

如果你不是 QQ 登录，把：

```env
ACCTYPE=qc
```

改成：

```env
ACCTYPE=wx
```

如果想看调试日志：

```env
DEBUG_LOG=true
```

如果你的前端部署在别的域名，建议设置 CORS：

```env
CORS_ORIGIN=https://your-site.com
```

开发测试想全放开可以临时写：

```env
CORS_ORIGIN=*
```

### 3. 启动

```bash
npm start
```

启动后打开：

- 首页：<http://localhost:3010>
- 健康检查：<http://localhost:3010/health>

---

## 二、API 用法

### POST 方式

`POST /api/prices/latest`

Body:

```json
{
  "objectIds": [15080050106, 15080050015, 15080050012]
}
```

示例：

```bash
curl -X POST 'http://localhost:3010/api/prices/latest' \
  -H 'content-type: application/json' \
  -d '{"objectIds":[15080050106,15080050015,15080050012]}'
```

### GET 方式

`GET /api/prices/latest?ids=15080050106,15080050015,15080050012`

示例：

```bash
curl 'http://localhost:3010/api/prices/latest?ids=15080050106,15080050015,15080050012'
```

---

## 三、成功返回示例

```json
{
  "ok": true,
  "cached": false,
  "upstreamStatus": 200,
  "ret": 0,
  "iRet": 0,
  "sMsg": "succ",
  "sAmsSerial": "AMS-...",
  "items": [
    { "id": "15080050106", "avgPrice": 24056 },
    { "id": "15080050015", "avgPrice": 62805 },
    { "id": "15080050012", "avgPrice": 15820 }
  ],
  "prices": {
    "15080050106": 24056,
    "15080050015": 62805,
    "15080050012": 15820
  }
}
```

## 四、失败返回示例

如果上游返回未登录或凭证失效，代理会返回更明确的错误：

```json
{
  "ok": false,
  "error": "上游返回未登录或凭证已失效",
  "ret": 101,
  "iRet": 101,
  "sMsg": "非常抱歉，请先登录！",
  "sAmsSerial": "AMS-..."
}
```

---

## 五、Docker 部署

### 1. 准备 `.env`

先确保当前目录有 `.env` 文件，并填好你的真实环境变量。

### 2. 构建并启动

```bash
docker compose up -d --build
```

### 3. 查看日志

```bash
docker compose logs -f
```

### 4. 停止服务

```bash
docker compose down
```

默认映射端口：

- `3010:3010`

访问：

- `http://服务器IP:3010`

---

## 六、直接用 Docker 命令

### 构建镜像

```bash
docker build -t item-price-proxy .
```

### 运行容器

```bash
docker run -d \
  --name item-price-proxy \
  --restart unless-stopped \
  --env-file .env \
  -p 3010:3010 \
  item-price-proxy
```

---

## 七、Nginx 反向代理示例

如果你有域名，可以把它挂到 Nginx 后面：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:3010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 八、说明

- 默认带了 60 秒内存缓存，避免重复打上游接口。
- 支持 GET / POST 两种方式，前端接入更方便。
- 返回里额外提供了 `prices`，方便网站直接按 ID 取值。
- 支持通过 `CORS_ORIGIN` 控制跨域。
- 不要把真实 `.env` 提交到公开仓库。
