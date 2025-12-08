import { AzureKeyCredential, OpenAIClient} from '@azure/openai';
import { propagateServerField } from 'next/dist/server/lib/render-server';

export const getChatCompletions = async (
    systemMessage: string,
    message: string,
    images: string[]
): Promise<any[]> => {
    return new Promise(async (resolve, reject) => {
        const endpoint = process.env.AZURE_OPENAI_ENDPOINT!
        const azureApiKey = process.env.AZURE_OPENAI_API_KEY!
        const deploymentId = process.env.AZURE_OPENAI_DEPLOYMENT_ID!

        const client = new OpenAIClient(
            endpoint,
            new AzureKeyCredential(azureApiKey)
        )

        let messages;

        if(images.length > 0){
            try{
                const response = await client.getChatCompletions(
                    deploymentId,[
                        {role: 'system', content: systemMessage},
                        {role: 'user', content: message},
                        {
                            role: 'user',
                            content: [
                                {type: 'image_url', imageUrl: {
                                    url: `data:image/jpeg;base64,${images[0]}`
                                }
                                }
                            ]
                        }
                    ],
                    {maxTokens: 4096}
                )
                resolve(response.choices)
            } catch(error){
                reject(error)
            }
        } else {
            try{
                const response = await client.getChatCompletions(
                    deploymentId,
                    [
                        {role: 'system', content: systemMessage},
                        {role: 'user', content: message},
                    ],
                    {maxTokens: 4096}
                );
                resolve(response.choices)
            }catch(error: any){
                reject(error)
            }
        }
    })
}

export const getEmbedding = async (message: string): Promise<number[]> => {
    return new Promise(async (resolve, reject) => {
        const endpoint = process.env.AZURE_OPENAI_ENDPOINT!
        const azureApiKey = process.env.AZURE_OPENAI_API_KEY!
        const deploymentId = process.env.AZURE_OPENAI_VEC_DEPLOYMENT_ID!

        const client = new OpenAIClient(
            endpoint,
            new AzureKeyCredential(azureApiKey)
        )

        const embedding = await client.getEmbeddings(deploymentId, [message]);
        resolve(embedding.data[0].embedding)
    })
}