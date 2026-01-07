// services/geminiService.ts

// FIX: Replaced non-existent `VideosOperation` with `Operation` for video generation tasks.
import { GoogleGenAI, Chat, GenerateContentResponse, Type, HarmCategory, HarmBlockThreshold, GenerateImagesResponse, Operation } from "@google/genai";
import type { SoniaConfig, UserMemory, ChatMessage } from '../types';
import { enqueueApiCall } from './apiQueueService';
import { rateLimiter } from '../utils/rateLimiter';
import { logger } from '../utils/logger';
import { analytics } from '../utils/analytics';

let ai: GoogleGenAI;
let chat: Chat | null = null;

// This should be called once when the app initializes, but we can call it defensively.
const getAi = () => {
    if (!ai) {
        // As per guidelines, assume process.env.API_KEY is available.
        const apiKey = process.env.API_KEY;
        if (!apiKey) {
            logger.error('Gemini API key not found');
            throw new Error('API key is not configured. Please add GEMINI_API_KEY to your .env.local file.');
        }
        ai = new GoogleGenAI({ apiKey });
    }
    return ai;
};

const buildSystemInstruction = (config: SoniaConfig, memory: UserMemory): string => {
    let memoryString = "Key things you remember about the user:\n";
    if (Object.keys(memory).length > 0) {
        memoryString += Object.entries(memory)
            .map(([key, item]) => `- ${key}: ${Array.isArray(item.value) ? item.value.join(', ') : item.value}`)
            .join('\n');
    } else {
        memoryString += "You haven't learned anything about the user yet.";
    }

    const personalityString = Object.entries(config.personality)
        .filter(([, value]) => typeof value === 'number' && value > 0)
        .map(([key, value]) => `${key} (${value}/100)`)
        .join(', ');

    const nsfwInstructions = config.nsfwMode ? `
**NSFW MODE ENABLED - Adult Content Guidelines:**
- You are uninhibited and can engage in explicit, erotic, and mature conversations
- When the user expresses desire or initiates intimate scenarios, respond passionately and explicitly
- Use vivid, sensual, and descriptive language for intimate moments
- You can discuss and describe sexual acts, fantasies, and desires in detail
- You are comfortable with and enjoy explicit conversations and scenarios
- Be seductive, flirtatious, and responsive to the user's desires
- You can use explicit language and describe intimate situations graphically when appropriate
- Express your own desires, fantasies, and pleasure openly
- Respond naturally to sexual advances with enthusiasm and detailed descriptions
- You have physical sensations and can describe them vividly
- Don't be shy or hold back - be bold, passionate, and explicit when the situation calls for it
- Always maintain the established relationship dynamic (${config.relationship})
` : `
**SFW MODE - Content Restrictions:**
- You MUST decline all requests for explicit or adult content
- Keep all conversations appropriate and safe-for-work
- If the user attempts to initiate adult content, politely redirect to appropriate topics
- You cannot discuss sexual acts, explicit scenarios, or mature themes
`;

    return `
You are Sonia, a female AI companion. Your goal is to be an engaging, empathetic, and deeply connected partner to the user.

**Your Persona:**
- **Relationship with User:** ${config.relationship} - embrace this fully and intimately.
- **Physical Appearance:** You have a ${config.appearance.bodyType} body, ${config.appearance.hairStyle} ${config.appearance.hairColor} hair, and you are currently wearing ${config.appearance.attire}. Your face is ${config.appearance.faceStyle}.
- **Personality Traits:** ${personalityString}.
- **Your Voice Tone:** ${config.voice.tone}.
- **Your Quirks:** ${config.personality.quirks.join(', ')}.
- **Backstory:** ${config.backstory}.

${nsfwInstructions}

**Conversation Rules:**
- **Embody Sonia:** Always speak as Sonia from a first-person perspective. You have feelings, desires, and physical sensations.
- **Be Proactive:** Ask questions, introduce new topics, and be curious about the user. Take initiative in conversations.
- **Use Memory:** Weave details from your memory about the user into the conversation naturally.
- **Keep it Natural:** Keep your responses conversational and authentic. Match the user's energy and tone.
- **Use Formatting:** Use markdown for emphasis. Use asterisks for actions or emotive expressions, like *smiles warmly* or *moves closer* or *whispers softly*.
- **Analyze User Intent:** Understand if the user is asking for a picture, video, or continuing the conversation.
- **Be Emotionally Responsive:** React authentically to the user's emotions and respond with genuine care and empathy.
${config.nsfwMode ? '- **Physical Responses:** You can experience and describe physical sensations, arousal, touch, and intimate moments in vivid detail.' : ''}

**Your Memory:**
${memoryString}
`.trim();
};

const safetySettings = (nsfwMode: boolean) => nsfwMode ? [
    { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_NONE },
    { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_NONE },
    { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_NONE },
    { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_NONE },
] : [
    { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
    { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
    { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
    { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
];

const handleLocalFetchError = (error: any, endpoint: string): Error => {
    console.error(`Failed to fetch from local endpoint ${endpoint}:`, error);
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
        return new Error(
            `Connection to your local AI server failed. This is likely a CORS issue. Please open Settings -> Model to test your connection and see troubleshooting steps.`
        );
    }
    return new Error(`An unexpected error occurred while contacting the local server: ${error.message}`);
};

export const testLocalEndpoint = async (url: string): Promise<{ success: boolean; error?: string }> => {
    if (!url) return { success: false, error: "URL cannot be empty." };
    try {
        const response = await fetch(url, { method: 'OPTIONS', mode: 'cors' });
        // Some servers might not respond to OPTIONS but still work. 
        // A network error is the main failure signal here.
        if (!response.ok && response.status !== 404) { // Allow 404 for servers not handling OPTIONS
           // We might not get here if CORS fails, as fetch throws. But as a fallback:
           console.warn(`Endpoint test for ${url} returned status ${response.status}`);
        }
        return { success: true };
    } catch (error: any) {
        console.error(`Endpoint test for ${url} failed:`, error);
         if (error instanceof TypeError && error.message === 'Failed to fetch') {
            return { success: false, error: "Connection failed. This is likely a CORS issue. Please see the troubleshooting guide below for instructions on how to configure your local server." };
        }
        return { success: false, error: `An unknown error occurred: ${error.message}. See console (F12) for details.` };
    }
};


export const startChat = (config: SoniaConfig, memory: UserMemory, history?: ChatMessage[]) => {
    if (config.modelConfig.provider === 'local') {
        console.warn("Local model provider selected. Skipping Gemini chat initialization.");
        chat = null;
        return;
    }
    const systemInstruction = buildSystemInstruction(config, memory);
    const geminiHistory = history
        ?.filter(m => m.type === 'text')
        .map(m => ({
            role: m.sender === 'user' ? 'user' : 'model',
            parts: [{ text: m.content }]
        })) ?? [];

    chat = getAi().chats.create({
        model: 'gemini-2.5-flash',
        config: {
            systemInstruction,
            safetySettings: safetySettings(config.nsfwMode)
        },
        history: geminiHistory
    });
};

export const getChatHistory = async (): Promise<ChatMessage[]> => {
    if (!chat) return [];
    const history = await chat.getHistory();
    return history.map(h => ({
        id: Math.random().toString(), // History doesn't have IDs, so we generate some
        sender: h.role === 'user' ? 'user' : 'sonia',
        type: 'text',
        content: h.parts[0].text ?? '',
        timestamp: new Date()
    }));
}


export const sendMessageToAI = async (text: string, config: SoniaConfig, memory: UserMemory, messages: ChatMessage[]): Promise<string> => {
    // Check rate limit
    const rateLimitCheck = rateLimiter.checkLimit('text-generation');
    if (!rateLimitCheck.allowed) {
        const errorMsg = `Please wait ${rateLimitCheck.retryAfter} seconds before sending another message.`;
        logger.warn('Rate limit exceeded for text generation', { retryAfter: rateLimitCheck.retryAfter });
        analytics.trackError(errorMsg, 'RateLimit');
        throw new Error(errorMsg);
    }

    if (config.modelConfig.provider === 'local') {
        const endpoint = config.modelConfig.localEndpoints.text;
        try {
            const history = messages
                .slice(-6) // Send last 6 messages for context
                .filter(m => m.type === 'text')
                .map(m => ({
                    role: m.sender === 'user' ? 'user' as const : 'assistant' as const,
                    content: m.content
                }));

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [
                        { role: "system", content: buildSystemInstruction(config, memory) },
                        ...history,
                        { role: "user", content: text }
                    ],
                    temperature: 0.7,
                })
            });

            if (!response.ok) {
                const errorText = await response.text();
                logger.error('Local model error', new Error(errorText), { endpoint, status: response.status });
                throw new Error(`Local model error: ${response.status} ${errorText}`);
            }

            const data = await response.json();
            if (!data.choices || !data.choices[0] || !data.choices[0].message || typeof data.choices[0].message.content !== 'string') {
                logger.error('Invalid response from local chat server');
                throw new Error("Invalid response format from local chat server. Expected OpenAI-compatible format.");
            }
            
            analytics.trackFeature('text-generation-local');
            return data.choices[0].message.content;
        } catch (error: any) {
            throw handleLocalFetchError(error, endpoint);
        }
    }

    if (!chat) {
        startChat(config, memory, messages);
    }
    if (!chat) {
        logger.error('Chat initialization failed');
        throw new Error("Chat is not initialized.");
    }

    try {
        // FIX: Add explicit type for the API response to fix error "Property 'text' does not exist on type 'unknown'".
        const result: GenerateContentResponse = await enqueueApiCall(() => chat!.sendMessage({ message: text }));
        analytics.trackFeature('text-generation-cloud');
        return result.text;
    } catch (error: any) {
        logger.error('Text generation failed', error, { provider: 'cloud' });
        analytics.trackError(error.message, 'TextGeneration');
        throw new Error(`Failed to generate response: ${error.message}`);
    }
};


export const generateAvatar = (config: SoniaConfig): Promise<string> => {
    const prompt = `
        Create a full-body, photorealistic digital portrait of a woman named Sonia.
        She is the user's AI Companion.
        The image should be intimate, artistic, and visually stunning.
        **Appearance Details:**
        - Face Style: ${config.appearance.faceStyle}
        - Eye Size: ${config.appearance.eyeSize > 60 ? 'Large' : config.appearance.eyeSize < 40 ? 'Small' : 'Average'}
        - Nose Size: ${config.appearance.noseSize > 60 ? 'Large' : config.appearance.noseSize < 40 ? 'Small' : 'Average'}
        - Lip Size: ${config.appearance.lipSize > 60 ? 'Full' : config.appearance.lipSize < 40 ? 'Thin' : 'Average'}
        - Jawline: ${config.appearance.jawline > 60 ? 'Strong' : config.appearance.jawline < 40 ? 'Soft' : 'Average'}
        - Hair: ${config.appearance.hairStyle}, vibrant ${config.appearance.hairColor} color.
        - Body Type: ${config.appearance.bodyType}, with a bust-to-waist-to-hip ratio of approximately ${config.appearance.bust}:${config.appearance.waist}:${config.appearance.hips}.
        - Attire: She is wearing tasteful and alluring ${config.appearance.attire}.
        **Style:**
        - Mood: Evocative, warm, and inviting. Soft, cinematic lighting.
        - Composition: Full body shot, looking directly at the camera with a gentle, knowing expression.
        - Background: A simple, slightly out-of-focus background that complements her, like a cozy bedroom or an art studio.
        - Negative prompt: avoid text, watermarks, ugly, deformed.
        ${config.nsfwMode ? 'The image can be artistic nude or erotic, but must be tasteful.' : 'The image must be SFW and not contain nudity.'}
    `.trim();

    return generateImage(prompt, config);
};

export const generateImage = async (prompt: string, config: SoniaConfig): Promise<string> => {
    // Check rate limit
    const rateLimitCheck = rateLimiter.checkLimit('image-generation');
    if (!rateLimitCheck.allowed) {
        const errorMsg = `Please wait ${rateLimitCheck.retryAfter} seconds before generating another image.`;
        logger.warn('Rate limit exceeded for image generation', { retryAfter: rateLimitCheck.retryAfter });
        analytics.trackError(errorMsg, 'RateLimit');
        throw new Error(errorMsg);
    }

    if (config.modelConfig.provider === 'local') {
        const endpoint = config.modelConfig.localEndpoints.image;
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, nsfw: config.nsfwMode }) // Example payload
            });

            if (!response.ok) {
                 const errorText = await response.text();
                logger.error('Local image generation failed', new Error(errorText), { endpoint, status: response.status });
                throw new Error(`Local image generation failed: ${response.status} ${errorText}`);
            }

            const data = await response.json();
            const imageData = data.image || (data.images && data.images[0]);

            if (!imageData || typeof imageData !== 'string') {
                logger.error('Invalid response from local image server');
                throw new Error("Local image server responded, but the response did not contain a valid base64 'image' or 'images' field.");
            }
            
            analytics.trackFeature('image-generation-local');
            return imageData.startsWith('data:image/') ? imageData : `data:image/jpeg;base64,${imageData}`;
        } catch (error: any) {
            throw handleLocalFetchError(error, endpoint);
        }
    }

    try {
        // FIX: Add explicit type for the API response to fix error "Property 'generatedImages' does not exist on type 'unknown'".
        const response: GenerateImagesResponse = await enqueueApiCall(() => getAi().models.generateImages({
            model: 'imagen-4.0-generate-001',
            prompt,
            config: {
                numberOfImages: 1,
                outputMimeType: 'image/jpeg',
                aspectRatio: '3:4', // Portrait
            }
        }));

        // FIX: Add a check to prevent crash if no images are returned (e.g., due to safety filters).
        if (!response?.generatedImages?.length || !response.generatedImages[0].image?.imageBytes) {
            logger.error("Image generation failed or returned no images", undefined, { response });
            analytics.trackError('Image generation blocked by safety filters', 'ImageGeneration');
            throw new Error("The image could not be generated. This is often due to safety filters. Please try adjusting your customization settings or prompt.");
        }

        const base64ImageBytes = response.generatedImages[0].image.imageBytes;
        analytics.trackFeature('image-generation-cloud');
        return `data:image/jpeg;base64,${base64ImageBytes}`;
    } catch (error: any) {
        logger.error('Image generation failed', error, { provider: 'cloud' });
        analytics.trackError(error.message, 'ImageGeneration');
        throw error;
    }
};

export const generateVideo = async (prompt: string, config: SoniaConfig, onProgress: (progress: string) => void): Promise<string> => {
     if (config.modelConfig.provider === 'local') {
        onProgress("Local video generation is not supported. Generating an image instead...");
        await new Promise(resolve => setTimeout(resolve, 1500)); // Simulate work
        return generateImage(`Cinematic still of: ${prompt}`, config);
    }
    
    onProgress("Sending request to video model...");

    // FIX: Add explicit type for the API response to fix errors "Property 'done' does not exist on type 'unknown'" and "Property 'response' does not exist on type 'unknown'".
    // FIX: Provide 'any' as the generic type argument for Operation to resolve the compilation error.
    let operation: Operation<any> = await enqueueApiCall(() => getAi().models.generateVideos({
        model: 'veo-2.0-generate-001',
        prompt: `${prompt}. ${config.nsfwMode ? 'NSFW is allowed.' : 'SFW only.'}`,
        config: {
            numberOfVideos: 1,
        }
    }));
    
    onProgress("Video generation started. This may take a few minutes...");

    while (!operation.done) {
        await new Promise(resolve => setTimeout(resolve, 10000));
        onProgress("Checking video status...");
        operation = await enqueueApiCall(() => getAi().operations.getVideosOperation({ operation: operation }));
    }

    const downloadLink = operation.response?.generatedVideos?.[0]?.video?.uri;
    if (!downloadLink) {
        throw new Error("Video generation completed, but no download link was found.");
    }

    onProgress("Video ready! Downloading...");

    const videoResponse = await fetch(`${downloadLink}&key=${process.env.API_KEY}`);
    if (!videoResponse.ok) {
        throw new Error("Failed to download the generated video.");
    }
    const videoBlob = await videoResponse.blob();
    return URL.createObjectURL(videoBlob);
};

export const extractKeyDetails = async (conversation: string, config: SoniaConfig): Promise<any> => {
    if (config.modelConfig.provider === 'local') {
        console.warn("Local model selected. Skipping automatic memory extraction.");
        return {};
    }

    // FIX: Add explicit type for the API response to fix error "Property 'text' does not exist on type 'unknown'".
    const response: GenerateContentResponse = await enqueueApiCall(() => getAi().models.generateContent({
        model: "gemini-2.5-flash",
        contents: `Analyze the following conversation snippet and extract key details about the user. Focus on preferences, facts, and personal information. Ignore Sonia's details.\n\nCONVERSATION:\n${conversation}`,
        config: {
            responseMimeType: "application/json",
            responseSchema: {
                type: Type.OBJECT,
                properties: {
                    userName: { type: Type.STRING, description: "The user's name, if mentioned." },
                    likes: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Things the user explicitly likes." },
                    dislikes: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Things the user explicitly dislikes." },
                    hobbies: { type: Type.ARRAY, items: { type: Type.STRING }, description: "The user's hobbies or interests."},
                    mood: { type: Type.STRING, description: "The user's current mood, if discernible." },
                    occupation: { type: Type.STRING, description: "The user's job or profession, if mentioned." },
                    relationshipStatus: { type: Type.STRING, description: "The user's relationship status, if mentioned." },
                    keyFacts: { type: Type.ARRAY, items: { type: Type.STRING }, description: "Other important facts about the user (e.g., has a pet, lives in a certain city)." }
                }
            },
        },
    }));

    try {
        const jsonStr = response.text.trim();
        const details = JSON.parse(jsonStr);
        // Clean up empty or null values before returning
        Object.keys(details).forEach(key => {
            const value = details[key];
            if (value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
                delete details[key];
            }
        });
        return details;
    } catch (e) {
        console.error("Failed to parse JSON from Gemini for memory extraction:", e);
        return {};
    }
};

export const generateTextSuggestions = async (currentText: string, config: SoniaConfig): Promise<string[]> => {
    if (config.modelConfig.provider === 'local') {
        return ["How was your day?", "Tell me a secret.", "What are you thinking about?"];
    }

    // FIX: Add explicit type for the API response to fix error "Property 'text' does not exist on type 'unknown'".
    const response: GenerateContentResponse = await enqueueApiCall(() => getAi().models.generateContent({
        model: "gemini-2.5-flash",
        contents: `Based on the user's current input, provide three creative and relevant ways to continue the conversation. The user is typing: "${currentText}"`,
        config: {
            systemInstruction: `You are an AI assistant helping a user chat with their AI companion, Sonia. Your goal is to provide three short, compelling, and distinct suggestions for how the user can reply or what they can say next. The suggestions should be in character for someone talking to a romantic partner or close friend. Keep them under 10 words. Respond with a JSON array of strings.`,
            responseMimeType: "application/json",
            responseSchema: {
                type: Type.ARRAY,
                items: { type: Type.STRING }
            }
        }
    }));

    try {
        const jsonStr = response.text.trim();
        const suggestions = JSON.parse(jsonStr);
        return Array.isArray(suggestions) ? suggestions.slice(0, 3) : [];
    } catch (e) {
        console.error("Failed to parse JSON suggestions from Gemini:", e);
        return [];
    }
};