/**
 * @piloci/sdk — TypeScript SDK for the piLoci self-hosted memory server.
 *
 * Re-exports the main client class, all error classes, and all public types.
 */

export { Piloci } from "./client.js";

export {
  PilociError,
  PilociAuthError,
  PilociPermissionError,
  PilociValidationError,
  PilociServerError,
} from "./errors.js";

export type {
  PilociClientOptions,
  MemoryAction,
  MemorySaveInput,
  MemoryForgetInput,
  MemorySaveResult,
  MemoryForgetResult,
  RecallInput,
  RecallResult,
  RecallPreviewResult,
  RecallFullResult,
  RecallFileResult,
  MemoryPreview,
  ListProjectsInput,
  ListProjectsResult,
  ProjectInfo,
  WhoAmIResult,
  InitInput,
  InitResult,
  RecommendInput,
  RecommendResult,
  InstinctInfo,
  ContradictInput,
  ContradictResult,
} from "./types.js";
