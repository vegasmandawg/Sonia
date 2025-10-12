// services/whisperService.ts
import type { SoniaConfig } from '../types';

const handleLocalFetchError = (error: any, endpoint: string): Error => {
    console.error(`Failed to fetch from local endpoint ${endpoint}:`, error);
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
        return new Error(
            `Connection to your local AI server failed. This is likely a CORS issue. Please open Settings -> Model to test your connection and see troubleshooting steps.`
        );
    }
    return new Error(`An unexpected error occurred while contacting the local server: ${error.message}`);
};

/**
 * Transcribes an audio blob using the configured local endpoint.
 * @param audioBlob The audio data to transcribe.
 * @param config The application configuration containing the endpoint URL.
 * @returns A promise that resolves to the transcribed text.
 */
export const transcribeAudio = async (audioBlob: Blob, config: SoniaConfig): Promise<string> => {
    if (config.modelConfig.provider !== 'local') {
        throw new Error("Cloud-based audio transcription is not configured. Please switch to a local provider in Settings.");
    }
    
    const endpoint = config.modelConfig.localEndpoints.audio;
    if (!endpoint) {
        throw new Error("Local audio transcription endpoint is not defined in the configuration.");
    }

    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData,
            // Note: Don't set 'Content-Type' header when using FormData with fetch.
            // The browser will set it correctly, including the boundary.
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Transcription server error: ${response.status} - ${errorText}`);
        }

        const result = await response.json();
        
        // The structure of the response depends on the API.
        // We'll assume a common structure like { "text": "..." }.
        if (typeof result.text !== 'string') {
            throw new Error("Invalid response format from transcription server.");
        }

        return result.text;
    } catch (error: any) {
        throw handleLocalFetchError(error, endpoint);
    }
};