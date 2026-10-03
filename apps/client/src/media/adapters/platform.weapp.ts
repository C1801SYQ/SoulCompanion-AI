import { WeAppMediaCaptureAdapter } from './weapp';
import type { MediaCaptureAdapter } from '../types';

export function createMediaCaptureAdapter(): MediaCaptureAdapter { return new WeAppMediaCaptureAdapter(); }
