from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes.userRoutes import router as userRoutes
from src.routes.targetCustomersRoutes import router as targetCustomersRoutes

# Create FastAPI app
app = FastAPI(
    title="Sales Buddy API",
    description="Backend API for Sales Buddy",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(userRoutes, prefix="/api/user")
app.include_router(targetCustomersRoutes, prefix="/api/target-customers")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}