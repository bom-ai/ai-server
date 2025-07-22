from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import numpy as np
from typing import Optional, List
import uvicorn

# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="BOMScript Server",
    description="FastAPI 서버 for BOMScript",
    version="1.0.0"
)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터 모델 정의
class Item(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: float
    quantity: int

class ItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    quantity: int

# 임시 데이터 저장소 (실제 환경에서는 데이터베이스 사용)
items_db = []
next_id = 1

# 기본 엔드포인트
@app.get("/")
async def root():
    return {"message": "Welcome to BOMScript Server!", "status": "running"}

# Health check 엔드포인트
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": pd.Timestamp.now().isoformat()}

# 모든 아이템 조회
@app.get("/items", response_model=List[ItemResponse])
async def get_items():
    return items_db

# 특정 아이템 조회
@app.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    for item in items_db:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")

# 새 아이템 생성
@app.post("/items", response_model=ItemResponse)
async def create_item(item: Item):
    global next_id
    new_item = {
        "id": next_id,
        "name": item.name,
        "description": item.description,
        "price": item.price,
        "quantity": item.quantity
    }
    items_db.append(new_item)
    next_id += 1
    return new_item

# 아이템 업데이트
@app.put("/items/{item_id}", response_model=ItemResponse)
async def update_item(item_id: int, item: Item):
    for i, existing_item in enumerate(items_db):
        if existing_item["id"] == item_id:
            updated_item = {
                "id": item_id,
                "name": item.name,
                "description": item.description,
                "price": item.price,
                "quantity": item.quantity
            }
            items_db[i] = updated_item
            return updated_item
    raise HTTPException(status_code=404, detail="Item not found")

# 아이템 삭제
@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    for i, item in enumerate(items_db):
        if item["id"] == item_id:
            deleted_item = items_db.pop(i)
            return {"message": f"Item {item_id} deleted successfully"}
    raise HTTPException(status_code=404, detail="Item not found")

# 데이터 분석 엔드포인트 (pandas/numpy 활용)
@app.get("/analytics/summary")
async def get_analytics_summary():
    if not items_db:
        return {"message": "No data available for analysis"}
    
    df = pd.DataFrame(items_db)
    
    summary = {
        "total_items": len(df),
        "total_value": float(df["price"].sum()),
        "average_price": float(df["price"].mean()),
        "total_quantity": int(df["quantity"].sum()),
        "price_statistics": {
            "min": float(df["price"].min()),
            "max": float(df["price"].max()),
            "std": float(df["price"].std()) if len(df) > 1 else 0.0
        }
    }
    
    return summary

# 서버 실행 (개발용)
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # 개발 모드에서 자동 리로드
    )