from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["productsRoutes"])

class CreateProductRequest(BaseModel):
    name: str
    description: str
    price: float
    quantity: int

class ChatQuery(BaseModel):
    query: str

@router.post("/chat")
async def chat(query: ChatQuery):
    return {"message": query}