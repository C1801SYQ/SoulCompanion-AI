import { WebMediaCaptureAdapter } from './web';
import type { MediaCaptureAdapter } from '../types';

export function createMediaCaptureAdapter(): MediaCaptureAdapter { return new WebMediaCaptureAdapter(); }
