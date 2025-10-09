# discovery/models.py
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Column, String, Integer, DateTime, Text, ForeignKey

# ---------- Article (existing / canonical) ----------
class Article(SQLModel, table=True):
    __tablename__ = "articles"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: Optional[str] = Field(default=None, sa_column=Column("title", String(length=1024)))
    canonical_url: Optional[str] = Field(default=None, index=True, sa_column=Column("canonical_url", String(length=2048), unique=True))
    source: Optional[str] = Field(default=None, sa_column=Column("source", String(length=255), index=True))
    authors: Optional[str] = Field(default=None, sa_column=Column("authors", String(length=1024)))
    published_at: Optional[datetime] = Field(default=None, sa_column=Column("published_at", DateTime))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("created_at", DateTime))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("updated_at", DateTime))
    cleaned_text: Optional[str] = Field(default=None, sa_column=Column("cleaned_text", Text))
    short_summary: Optional[str] = Field(default=None, sa_column=Column("short_summary", Text))
    top_image_url: Optional[str] = Field(default=None, sa_column=Column("top_image_url", String(length=2048)))
    content_hash: Optional[str] = Field(default=None, sa_column=Column("content_hash", String(length=128), index=True))
    word_count: Optional[int] = Field(default=None, sa_column=Column("word_count", Integer))

    # reverse relation (not required, but convenient)
    section_items: list["SectionItem"] = Relationship(back_populates="article")  # type: ignore[name-defined]


# ---------- Section (a logical grouping for SectionItems) ----------
class Section(SQLModel, table=True):
    __tablename__ = "sections"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column("name", String(length=255)), index=True)
    seed_url: Optional[str] = Field(default=None, sa_column=Column("seed_url", String(length=2048), unique=True))
    description: Optional[str] = Field(default=None, sa_column=Column("description", String(length=1024)))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("created_at", DateTime))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("updated_at", DateTime))


# ---------- SectionItem (headline / teaser from section/list page) ----------
class SectionItem(SQLModel, table=True):
    __tablename__ = "section_items"
    id: Optional[int] = Field(default=None, primary_key=True)
    section_id: Optional[int] = Field(default=None, foreign_key="sections.id", sa_column=Column("section_id", Integer))
    title: Optional[str] = Field(default=None, sa_column=Column("title", String(length=1024)))
    teaser: Optional[str] = Field(default=None, sa_column=Column("teaser", Text))
    canonical_url: Optional[str] = Field(default=None, index=True, sa_column=Column("canonical_url", String(length=2048), unique=True))
    top_image_url: Optional[str] = Field(default=None, sa_column=Column("top_image_url", String(length=2048)))
    source: Optional[str] = Field(default=None, sa_column=Column("source", String(length=1024)))
    published_at: Optional[datetime] = Field(default=None, sa_column=Column("published_at", DateTime))
    discovered_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("discovered_at", DateTime))
    article_id: Optional[int] = Field(default=None, foreign_key="articles.id", sa_column=Column("article_id", Integer, ForeignKey("articles.id"), nullable=True, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("created_at", DateTime))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column("updated_at", DateTime))

    # relationship back to Article
    article: Optional[Article] = Relationship(back_populates="section_items")  # type: ignore[name-defined]

