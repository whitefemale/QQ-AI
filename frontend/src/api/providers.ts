/** 模型 Provider 测试与模型发现 API 客户端。 */

import { api } from '@/api/client'
import type { ProviderModelList, ProviderTestResult } from '@/api/types'

export interface TestRequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
}

export interface ConnectivityTestPayload {
  operation_id?: string
  prompt?: string
  max_output_tokens?: number
}

export interface GenerationTestPayload {
  operation_id?: string
  prompt: string
  max_output_tokens?: number
  temperature?: number
}

export interface CancelOperationResult {
  found: boolean
  operation_id: string
  message: string
}

export function listProviderModels(
  providerId: string,
  options: TestRequestOptions = {},
): Promise<ProviderModelList> {
  return api<ProviderModelList>(`/providers/${encodeURIComponent(providerId)}/models`, {
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? 30_000,
  })
}

export function testProviderConnectivity(
  providerId: string,
  payload: ConnectivityTestPayload = {},
  options: TestRequestOptions = {},
): Promise<ProviderTestResult> {
  return api<ProviderTestResult>(`/providers/${encodeURIComponent(providerId)}/test`, {
    method: 'POST',
    body: payload,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function testProviderGeneration(
  providerId: string,
  payload: GenerationTestPayload,
  options: TestRequestOptions = {},
): Promise<ProviderTestResult> {
  return api<ProviderTestResult>(`/providers/${encodeURIComponent(providerId)}/test-generation`, {
    method: 'POST',
    body: payload,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  })
}

export function cancelProviderOperation(
  providerId: string,
  operationId: string,
  options: TestRequestOptions = {},
): Promise<CancelOperationResult> {
  return api<CancelOperationResult>(
    `/providers/${encodeURIComponent(providerId)}/operations/${encodeURIComponent(operationId)}/cancel`,
    { method: 'POST', signal: options.signal, timeoutMs: options.timeoutMs ?? 5_000 },
  )
}

/** 显式传空字符串表示清除已保存 Key；后端会同时清空测试证据。 */
export function clearProviderApiKey(providerId: string): Promise<Record<string, unknown>> {
  return api(`/providers/${encodeURIComponent(providerId)}`, {
    method: 'PATCH',
    body: { api_key: '' },
  })
}
