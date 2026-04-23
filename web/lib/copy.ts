export const locales = ['ko', 'en'] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = 'ko';

const copy = {
  ko: {
    metadata: { description: '라즈베리파이를 위한 고성능 MCP 메모리 엔진' },
    common: { brandName: 'piLoci', login: '로그인', signup: '시작하기' },
    landing: {
      badge: 'MCP · HIGH-PERFORMANCE',
      titleLines: ['KNOWLEDGE MEMORY', 'FOR YOUR AI CORE'],
      descriptionLines: [
        'piLoci는 라즈베리파이와 같은 저전력 환경에서도 완벽하게 작동하는',
        'Model Context Protocol(MCP) 기반의 퍼스널 메모리 서버입니다.',
      ],
      stats: {
        latency: '2ms',
        reduction: '85%',
        uptime: '99.9%',
      },
      sections: {
        intro: {
          title: '소개',
          content: 'LLM과의 대화 맥락이 끊기는 문제에 지치셨나요? piLoci는 프로젝트별로 독립된 메모리 공간을 제공하여 AI가 당신의 의도와 과거 기록을 완벽하게 기억하도록 돕습니다. 로컬 우선(Local-first) 철학에 따라 모든 데이터는 당신의 장치 안에서만 머뭅니다.',
        },
        features: {
          title: '핵심 기능',
          list: [
            { title: '맥락 격리 (Context Isolation)', desc: '프로젝트나 주제별로 메모리를 분리하여 다른 작업과 맥락이 섞이는 것을 원천 차단합니다.' },
            { title: 'AST 기반 맥락 추출', desc: 'Tree-sitter를 활용하여 코드의 구조를 깊이 있게 이해하고 핵심 정보를 정밀하게 보존합니다.' },
            { title: '초저지연 검색', desc: 'SQLite Vector 확장을 사용하여 라즈베리파이에서도 2ms 이내의 빠른 검색 성능을 보장합니다.' },
            { title: '완전한 데이터 주권', desc: '클라우드 의존성 없이 100% 로컬에서 작동하며, 외부 유출 걱정 없는 안전한 환경을 제공합니다.' },
          ]
        },
        quickStart: {
          title: '빠른 시작',
          installTitle: '1. uvx를 이용한 설치',
          installDesc: '별도의 복잡한 설정 없이 다음 명령어로 즉시 서버를 실행할 수 있습니다.',
          setupTitle: '2. 백엔드 구성 (.env)',
          setupDesc: '환경 변수를 통해 SQLite 경로 및 인덱싱 엔진을 자유롭게 설정하세요.',
        },
        capabilities: {
          title: '제공되는 도구 (Tools)',
          desc: 'piLoci MCP 서버는 LLM이 직접 호출할 수 있는 다음과 같은 강력한 도구들을 제공합니다.',
          list: [
            { name: 'store_memory', desc: '새로운 정보나 프로젝트의 맥락을 영구 메모리에 저장합니다.' },
            { name: 'search_context', desc: '현재 작업과 가장 관련성이 높은 과거 기억을 시멘틱 검색으로 불러옵니다.' },
            { name: 'recall_project_state', desc: '특정 프로젝트의 전체적인 진행 상황과 상태를 요약하여 제공합니다.' },
          ]
        },
        pricing: {
          title: '영원한 무료, 완전한 자유',
          desc: 'piLoci는 커뮤니티와 함께 성장하는 오픈소스 프로젝트입니다. 어떤 비용이나 제약 없이 당신의 AI 코어를 강화하세요.',
          features: ['무제한 프로젝트 생성', '로컬 SQLite 저장소', '상업적 이용 가능 (MIT)', '개인 정보 추적 0%'],
        }
      },
      footer: '© 2026 piLoci — HIGH-PERFORMANCE MCP MEMORY ENGINE',
    },
    themeToggle: { toLightAriaLabel: '라이트 모드', toDarkAriaLabel: '다크 모드' }
  },
  en: {
    metadata: { description: 'High-performance MCP memory engine for Raspberry Pi' },
    common: { brandName: 'piLoci', login: 'Log in', signup: 'Get Started' },
    landing: {
      badge: 'MCP · HIGH-PERFORMANCE',
      titleLines: ['KNOWLEDGE MEMORY', 'FOR YOUR AI CORE'],
      descriptionLines: [
        'piLoci is a personal memory server based on Model Context Protocol(MCP)',
        'designed to run perfectly on low-power devices like Raspberry Pi.',
      ],
      stats: {
        latency: '2ms',
        reduction: '85%',
        uptime: '99.9%',
      },
      sections: {
        intro: {
          title: 'Introduction',
          content: 'Tired of losing context in LLM conversations? piLoci provides isolated memory spaces per project, helping AI remember your intentions and history perfectly. Based on a Local-first philosophy, all data stays only on your device.',
        },
        features: {
          title: 'Key Features',
          list: [
            { title: 'Context Isolation', desc: 'Separate memory by project or topic to prevent context mixing between tasks.' },
            { title: 'AST-based Extraction', desc: 'Deeply understand code structures using Tree-sitter and preserve key info precisely.' },
            { title: 'Ultra-low Latency', desc: 'Ensures fast search performance within 2ms even on Raspberry Pi using SQLite Vector.' },
            { title: 'Full Data Sovereignty', desc: 'Operates 100% locally without cloud dependency, providing a leak-proof secure environment.' },
          ]
        },
        quickStart: {
          title: 'Quick Start',
          installTitle: '1. Installation via uvx',
          installDesc: 'Run the server immediately with the following command without complex setup.',
          setupTitle: '2. Backend Config (.env)',
          setupDesc: 'Freely configure SQLite paths and indexing engines via environment variables.',
        },
        capabilities: {
          title: 'Available Tools',
          desc: 'piLoci MCP server provides the following powerful tools that LLMs can call directly.',
          list: [
            { name: 'store_memory', desc: 'Save new information or project context to permanent memory.' },
            { name: 'search_context', desc: 'Retrieve past memories most relevant to the current task via semantic search.' },
            { name: 'recall_project_state', desc: 'Provides a summarized overview of the overall progress and state of a specific project.' },
          ]
        },
        pricing: {
          title: 'Always Free, Total Freedom',
          desc: 'piLoci is an open-source project growing with the community. Enhance your AI core without any costs or restrictions.',
          features: ['Unlimited Projects', 'Local SQLite Storage', 'Commercial Use (MIT)', 'Zero Telemetry'],
        }
      },
      footer: '© 2026 piLoci — HIGH-PERFORMANCE MCP MEMORY ENGINE',
    },
    themeToggle: { toLightAriaLabel: 'Switch to light', toDarkAriaLabel: 'Switch to dark' }
  }
} as const;

export function getCopy(locale: Locale = defaultLocale) {
  return copy[locale];
}
