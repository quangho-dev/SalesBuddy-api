from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes.userRoutes import router as userRoutes
from src.routes.targetCustomersRoutes import router as targetCustomersRoutes
from src.routes.productsRoutes import router as productsRoutes
from src.routes.chatRoutes import router as chatRoutes
from src.routes.customerRoutes import router as customerRoutes
from src.routes.orderRoutes import router as orderRoutes
from src.routes.quoteRoutes import router as quoteRoutes
from src.routes.paymentRoutes import router as paymentRoutes
from src.routes.settingsRoutes import router as settingsRoutes

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
app.include_router(productsRoutes, prefix="/api/products")
app.include_router(chatRoutes, prefix="/api/chat")
app.include_router(customerRoutes, prefix="/api/customers")
app.include_router(orderRoutes, prefix="/api/orders")
app.include_router(quoteRoutes, prefix="/api/quotes")
app.include_router(paymentRoutes, prefix="/api/payments")
app.include_router(settingsRoutes, prefix="/api/settings")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}