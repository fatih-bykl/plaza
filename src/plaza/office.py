"""Plaza: departmanlardan ve çalışanlardan oluşan bir CrewAI ofisi."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml
from crewai import LLM, Agent, Crew, Process, Task

from .tools import build_tools

DEFAULT_MODEL = "anthropic/claude-opus-5-5"


@dataclass
class StaffSpec:
    key: str
    department: str
    role: str
    goal: str
    backstory: str
    tools: list[str]


def load_org(path: Path | None = None) -> dict:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("plaza.config").joinpath("departments.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def list_staff(org: dict, departments: list[str] | None = None) -> list[StaffSpec]:
    depts = org["departments"]
    if departments:
        unknown = set(departments) - depts.keys()
        if unknown:
            raise ValueError(
                f"Bilinmeyen departman(lar): {', '.join(sorted(unknown))}. "
                f"Mevcut: {', '.join(depts)}"
            )
        selected = {k: depts[k] for k in departments}  # kullanıcının verdiği sıra korunur
    else:
        selected = depts
    return [
        StaffSpec(
            key=s["key"],
            department=d["name"],
            role=s["role"],
            goal=s["goal"].strip(),
            backstory=s["backstory"].strip(),
            tools=s.get("tools", []),
        )
        for d in selected.values()
        for s in d["staff"]
    ]


def make_llm(model: str) -> LLM:
    # max_tokens açıkça veriliyor: çok büyük değerler akışsız (non-streaming) isteklerde
    # SDK zaman aşımı kontrolüne takılır. temperature verilmiyor (yeni modeller reddediyor).
    return LLM(model=model, max_tokens=16000)


def build_crew(
    request: str,
    process: str = "hierarchical",
    departments: list[str] | None = None,
    workdir: Path = Path("cikti"),
    org_file: Path | None = None,
    verbose: bool = True,
) -> Crew:
    org = load_org(org_file)
    staff = list_staff(org, departments)
    if not staff:
        raise ValueError("Seçilen departmanlarda çalışan yok.")

    manager_model = os.getenv("PLAZA_MANAGER_MODEL", os.getenv("PLAZA_MODEL", DEFAULT_MODEL))
    staff_model = os.getenv("PLAZA_STAFF_MODEL", os.getenv("PLAZA_MODEL", DEFAULT_MODEL))
    staff_llm = make_llm(staff_model)

    agents = [
        Agent(
            role=s.role,
            goal=s.goal,
            backstory=f"{s.backstory}\n{s.department} çalışanısın. Her zaman Türkçe yanıt verirsin.",
            tools=build_tools(s.tools, workdir),
            llm=staff_llm,
            allow_delegation=False,
            verbose=verbose,
        )
        for s in staff
    ]

    team = ", ".join(f"{s.role} ({s.department})" for s in staff)

    if process == "hierarchical":
        m = org["manager"]
        manager = Agent(
            role=m["role"],
            goal=m["goal"].strip(),
            backstory=m["backstory"].strip() + "\nHer zaman Türkçe yanıt verirsin.",
            llm=make_llm(manager_model),
            allow_delegation=True,
            verbose=verbose,
        )
        tasks = [
            Task(
                description=(
                    f"Plaza'ya gelen talep:\n\n{request}\n\n"
                    f"Ekibin: {team}.\n"
                    "Talebi alt işlere böl, her birini en uygun çalışana devret, çıktılarını denetle "
                    "ve eksik/hatalı olanları düzelttir. Dosya üretilmesi gerekiyorsa çalışanlara "
                    "dosyaları yazmalarını söyle."
                ),
                expected_output=(
                    "Talebi tam karşılayan nihai teslimat: yapılan işlerin özeti, hangi çalışanın "
                    "ne yaptığı, üretilen dosyaların listesi ve açık kalan konular."
                ),
            )
        ]
        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.hierarchical,
            manager_agent=manager,
            verbose=verbose,
        )

    if process == "sequential":
        tasks: list[Task] = []
        for spec, agent in zip(staff, agents):
            tasks.append(
                Task(
                    description=(
                        f"Plaza'ya gelen talep:\n\n{request}\n\n"
                        f"Sıralı bir iş akışındasın. Ekip sırası: {team}.\n"
                        f"Sen {spec.role} olarak kendi uzmanlık alanındaki katkıyı yap. "
                        "Önceki çalışanların çıktılarını temel al; gerekiyorsa dosyaları oku ve yaz."
                    ),
                    expected_output=f"{spec.role} olarak bu talebe katkının eksiksiz çıktısı.",
                    agent=agent,
                    context=list(tasks),  # önceki tüm çıktıları gör
                )
            )
        return Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=verbose)

    raise ValueError("process 'hierarchical' ya da 'sequential' olmalı.")
