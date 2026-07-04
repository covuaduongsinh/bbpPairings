# Triển khai giao diện web lên Vercel

Giao diện web (`webui/`) được deploy lên Vercel dưới dạng một **hàm serverless
Python** (`api/index.py`) tái dùng toàn bộ logic của `webui/server.py`, lưu trạng
thái giải trên **Upstash Redis (KV)**, và chạy một **binary Linux tĩnh** của
engine đã đóng gói sẵn tại `bin/bbpPairings`. Mỗi lần push lên GitHub, Vercel tự
động deploy.

## Kiến trúc

```
GitHub (push)  ──►  Vercel build  ──►  api/index.py (serverless)
                                          │  reuse webui/server.py routing
                                          │  engine: bin/bbpPairings → /tmp (+x)
                                          └─ state: Upstash Redis (KV) qua REST
```

- `vercel.json` — rewrite mọi route vào `api/index.py`; `includeFiles` đóng gói
  `webui/*.py`, `webui/index.html`, và `bin/bbpPairings`.
- `bin/bbpPairings` — engine Linux x86_64 **tĩnh hoàn toàn** (không phụ thuộc
  glibc). Không có đĩa bền trên Vercel nên hàm copy binary sang `/tmp` rồi chmod +x.
- Lưu trữ: `webui/store_kv.py` (Upstash REST), khóa lạc quan bằng Lua CAS.

## Các bước thiết lập (làm một lần)

1. **Đưa code lên GitHub** — đã có: `github.com/covuaduongsinh/bbpPairings`, nhánh
   `master`.

2. **Tạo Upstash Redis** (miễn phí):
   - Cách A (khuyến nghị, gọn nhất): trong Vercel → dự án → tab **Storage** →
     **Create Database** → **Upstash for Redis** (qua Marketplace). Vercel tự thêm
     các biến `KV_REST_API_URL` và `KV_REST_API_TOKEN` vào dự án.
   - Cách B: tạo tại console.upstash.com → copy **REST URL** và **REST TOKEN** →
     tự thêm vào Environment Variables của Vercel (xem bước 4).

3. **Import dự án vào Vercel:**
   - vercel.com → **Add New… → Project** → chọn repo `bbpPairings`.
   - Framework Preset: **Other** (Vercel tự nhận Python qua `requirements.txt`).
   - Root Directory: để mặc định (gốc repo). Không cần Build Command.
   - Bấm **Deploy**.

4. **Biến môi trường** (Project → Settings → Environment Variables):
   - `KV_REST_API_URL`, `KV_REST_API_TOKEN` — do Upstash/Marketplace đặt (bước 2A),
     hoặc tự dán (bước 2B). Cũng chấp nhận `UPSTASH_REDIS_REST_URL` /
     `UPSTASH_REDIS_REST_TOKEN`.
   - (Tùy chọn) `BBP_TIMEOUT` — giây tối đa mỗi lần gọi engine (mặc định 30).
   - (Tùy chọn) `BBP_TOKEN` — để **rỗng/không đặt** nghĩa là công khai. Khi cần
     bảo vệ, đặt một chuỗi bí mật; khi đó mọi request phải kèm `?token=<...>`
     hoặc header `X-Token: <...>` (bật đăng nhập sau này không cần đổi code).
   - Sau khi thêm/sửa biến, **Redeploy** để áp dụng.

5. **Xong.** Mở URL Vercel (vd `https://bbp-pairings.vercel.app`). Từ đây mỗi push
   lên `master` sẽ tự động deploy; pull request có preview deployment riêng.

## Cập nhật engine (khi đổi mã C++)

`bin/bbpPairings` là binary build sẵn nên phải build lại khi engine thay đổi:

```sh
# Trên Linux hoặc WSL Ubuntu (không dùng exe Windows):
make static=full            # binary Linux tĩnh hoàn toàn (-static)
cp bbpPairings.exe bin/bbpPairings   # tên .exe nhưng là ELF Linux
file bin/bbpPairings        # phải là "ELF ... statically linked"
ldd bin/bbpPairings         # phải báo "not a dynamic executable"
git add -f bin/bbpPairings && git commit -m "Cập nhật binary Linux cho Vercel"
git push                    # Vercel tự deploy
```

## Kiểm thử trước khi deploy

```sh
python webui/kv_test.py                     # KVStore + mock Upstash
# Sát môi trường Vercel nhất (chạy trong WSL/Linux, dùng binary Linux):
BBP_TEST_STORE=kv BBP_EXE=$PWD/bin/bbpPairings python3 webui/webui_test.py
```

## Lưu ý / giới hạn

- **Công khai:** hiện chưa bật đăng nhập — ai có link đều tạo/sửa/xóa giải được.
  Bật `BBP_TOKEN` bất cứ lúc nào (biến môi trường) mà không cần đổi code.
- **Cold start:** mỗi request spawn binary; chấp nhận được cho lưu lượng trọng
  tài. Giải rất lớn có thể cần tăng `maxDuration` trong `vercel.json`.
- **Đường dẫn định tuyến:** hàm định tuyến theo `self.path` dưới một rewrite
  bắt-tất. Nếu sau deploy route `/api/*` không nhận đúng, kiểm tra bằng
  `vercel dev` và điều chỉnh rewrite/handler.
