from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="manager")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanySettings(Base):
    __tablename__ = "company_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), default="UniC Plaquiste")
    legal_name: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    tax_id: Mapped[str] = mapped_column(String(64), default="")
    currency: Mapped[str] = mapped_column(String(8), default="")
    vat_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_validity_days: Mapped[int] = mapped_column(Integer, default=30)
    payment_terms: Mapped[str] = mapped_column(Text, default="")
    default_waste: Mapped[float] = mapped_column(Float, default=0.08)
    default_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    board_width_m: Mapped[float] = mapped_column(Float, default=1.20)
    board_height_m: Mapped[float] = mapped_column(Float, default=2.50)
    stud_spacing_m: Mapped[float] = mapped_column(Float, default=0.60)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    unit: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    waste_coefficient: Mapped[float] = mapped_column(Float, default=0.08)
    availability: Mapped[str] = mapped_column(String(64), default="unknown")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    prices: Mapped[list["MaterialPrice"]] = relationship(back_populates="material")


class MaterialPrice(Base):
    __tablename__ = "material_prices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # purchase | selling
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(255), default="saisie manuelle")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    material: Mapped[Material] = relationship(back_populates="prices")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(32), default="ens")
    selling_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    labor_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    location: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    description: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    customer: Mapped[Customer | None] = relationship()
    sites: Mapped[list["ConstructionSite"]] = relationship(back_populates="project")


class ConstructionSite(Base):
    __tablename__ = "construction_sites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="planned")
    progress_pct: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sites")
    tasks: Mapped[list["Task"]] = relationship(back_populates="site")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(ForeignKey("construction_sites.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open")
    assignee: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    site: Mapped[ConstructionSite] = relationship(back_populates="tasks")


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    currency: Mapped[str] = mapped_column(String(8), default="")
    subtotal: Mapped[float | None] = mapped_column(Float, nullable=True)
    vat_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    vat_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    prices_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    validity_days: Mapped[int] = mapped_column(Integer, default=30)
    payment_terms: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[str] = mapped_column(Text, default="")
    missing_info: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer | None] = relationship()
    project: Mapped[Project | None] = relationship()
    items: Mapped[list["QuotationItem"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    quotation_id: Mapped[str] = mapped_column(ForeignKey("quotations.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    material_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    data_status: Mapped[str] = mapped_column(String(16), default="confirmed")
    formula: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    quotation: Mapped[Quotation] = relationship(back_populates="items")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="invoice")
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    quotation_id: Mapped[str | None] = mapped_column(ForeignKey("quotations.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    currency: Mapped[str] = mapped_column(String(8), default="")
    subtotal: Mapped[float | None] = mapped_column(Float, nullable=True)
    vat_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    vat_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    paid: Mapped[float] = mapped_column(Float, default=0)
    remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer | None] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    method: Mapped[str] = mapped_column(String(64), default="")
    reference: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    currency: Mapped[str] = mapped_column(String(8), default="")
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    supplier: Mapped[Supplier | None] = relationship()
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    material_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    purchase_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    customer: Mapped[Customer | None] = relationship()
    items: Mapped[list["DeliveryNoteItem"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )


class DeliveryNoteItem(Base):
    __tablename__ = "delivery_note_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    note_id: Mapped[str] = mapped_column(ForeignKey("delivery_notes.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))

    note: Mapped[DeliveryNote] = relationship(back_populates="items")


class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="upload")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="ready")
    processing_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractedPage(Base):
    __tablename__ = "extracted_pages"
    __table_args__ = (UniqueConstraint("file_id", "page_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(ForeignKey("stored_files.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str] = mapped_column(String(64), default="document")
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(ForeignKey("stored_files.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128), default="application/pdf")
    path: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="Nouvelle conversation")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), default="general")
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255), default="UniC knowledge base")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Sequence(Base):
    __tablename__ = "sequences"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    to_addr: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    related_type: Mapped[str] = mapped_column(String(64), default="")
    related_id: Mapped[str] = mapped_column(String(36), default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CalculationTrace(Base):
    __tablename__ = "calculation_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    formula: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SocialAccount(Base):
    """Profil enregistré par plateforme. `linked` = profil noté, PAS une connexion API."""

    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    handle: Mapped[str] = mapped_column(String(255), default="")
    page_url: Mapped[str] = mapped_column(String(512), default="")
    linked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SocialPost(Base):
    """Publication ou réponse (commentaire, avis) en brouillon → revue → approuvé → publié (manuel)."""

    __tablename__ = "social_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="post")  # post | reply
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(String(512), default="")
    in_reply_to: Mapped[str] = mapped_column(Text, default="")  # texte du commentaire/avis visé
    status: Mapped[str] = mapped_column(String(16), default="draft")
    external_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InboxMessage(Base):
    """E-mail lu par IMAP (lecture seule). Contenu non fiable : jamais exécuté comme instruction."""

    __tablename__ = "inbox_messages"
    __table_args__ = (UniqueConstraint("uid", name="uq_inbox_uid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    uid: Mapped[str] = mapped_column(String(255), index=True)  # Message-ID ou UID IMAP
    from_addr: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    date: Mapped[str] = mapped_column(String(64), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    reply_draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
