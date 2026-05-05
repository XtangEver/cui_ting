# web/database.py
import os
import uuid
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "cui_ting.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(Text, nullable=False)
    video_id = Column(String, default="")
    title = Column(String, default="")
    status = Column(String, default="pending")
    raw_text = Column(Text, default="")
    refined_text = Column(Text, default="")
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


def create_task(url: str, video_id: str) -> Task:
    session = get_session()
    task = Task(url=url, video_id=video_id, title=video_id, status="pending")
    session.add(task)
    session.commit()
    session.refresh(task)
    session.close()
    return task


def get_task(task_id: str) -> Task | None:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    session.close()
    return task


def list_tasks() -> list[Task]:
    session = get_session()
    tasks = session.query(Task).order_by(Task.created_at.desc()).all()
    session.close()
    return tasks


def update_task(task_id: str, **kwargs) -> Task | None:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        for key, value in kwargs.items():
            setattr(task, key, value)
        task.updated_at = datetime.now()
        session.commit()
        session.refresh(task)
    session.close()
    return task


def delete_task(task_id: str) -> bool:
    session = get_session()
    task = session.query(Task).filter(Task.id == task_id).first()
    if task:
        session.delete(task)
        session.commit()
        session.close()
        return True
    session.close()
    return False
