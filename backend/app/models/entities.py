from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base

class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    facility_type: Mapped[str] = mapped_column(String(80), default="Health Center")
    district: Mapped[str] = mapped_column(String(100), index=True)
    province: Mapped[str] = mapped_column(String(100), default="")
    under5_population: Mapped[int] = mapped_column(Integer, default=0)
    poverty_rate: Mapped[float] = mapped_column(Float, default=0)
    malaria_prevalence: Mapped[float] = mapped_column(Float, default=0)
    stock_logs: Mapped[list["DailyStockLog"]] = relationship(back_populates="facility")

class Medicine(Base):
    __tablename__ = "medicines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(240))
    safety_days: Mapped[int] = mapped_column(Integer, default=14)
    stock_logs: Mapped[list["DailyStockLog"]] = relationship(back_populates="medicine")

class DailyStockLog(Base):
    __tablename__ = "daily_stock_logs"
    __table_args__ = (UniqueConstraint("facility_id", "medicine_id", "reporting_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    reporting_date: Mapped[str] = mapped_column(String(20), index=True)
    stock_units: Mapped[float] = mapped_column(Float)
    daily_consumption: Mapped[float] = mapped_column(Float)
    rainy_season: Mapped[int] = mapped_column(Integer, default=0)
    facility: Mapped[Facility] = relationship(back_populates="stock_logs")
    medicine: Mapped[Medicine] = relationship(back_populates="stock_logs")

class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lead_time_days: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
