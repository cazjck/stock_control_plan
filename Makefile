.PHONY: setup backend frontend test build api-types demo

setup:            ## cài backend (venv) và frontend (npm)
	./scripts/setup-backend.sh
	cd frontend && npm install

backend:          ## chạy API ở http://127.0.0.1:8000 (tự nạp lại khi sửa code)
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:         ## chạy giao diện ở http://localhost:5173 (proxy /api sang backend)
	cd frontend && npm run dev

demo:             ## chạy backend với dữ liệu mẫu, phục vụ luôn bản frontend đã build
	cd frontend && npm run build
	cd backend && BROKERS=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

test:             ## toàn bộ test backend và frontend
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npm test && npm run typecheck

build:
	cd frontend && npm run build

api-types:        ## sinh lại kiểu TypeScript sau khi đổi model hoặc route của backend
	cd backend && .venv/bin/python scripts/export_openapi.py
	cd frontend && npm run gen:api
