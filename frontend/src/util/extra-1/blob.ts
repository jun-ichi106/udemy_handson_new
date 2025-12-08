import {
    BlobServiceClient,
    StorageSharedKeyCredential
} from '@azure/storage-blob'

export const getBase64File = async(file_path: string) : Promise <string> => {
    return new Promise(async (resolve, reject) => {
        const sharedKeyCredential = new StorageSharedKeyCredential(
            process.env.AZURE_STORAGE_ACCOUNT_NAME!,
            process.env.AZURE_STORAGE_ACCOUNT_ACCESS_KEY!,
        )
        const blobServiceClient = new BlobServiceClient(
            `https://${process.env.AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net`,
            sharedKeyCredential
        )
        const containerClient = blobServiceClient.getContainerClient(
            process.env.AZURE_STORAGE_CONTAINER_NAME!
        )
        const blobClient = containerClient.getBlobClient(file_path)

        const downloadResponse = await blobClient.download(0)

        let encodedData = '';
        if(downloadResponse.readableStreamBody){
            const download = await streamToBuffer(
                downloadResponse.readableStreamBody
            )
            const encodedData = download.toString('base64')
            resolve(encodedData)
        }else{
            reject('readableStreamBody is undefined')
        }
    })
}

async function streamToBuffer(readableStream: NodeJS.ReadableStream):Promise<any> {
    return new Promise((resolve, reject) => {
        const chunks: any[] = [];
        readableStream.on('data', (data) => {
            chunks.push(data instanceof Buffer ? data : Buffer.from(data));
        })
        readableStream.on('end', () => {
            resolve(Buffer.concat(chunks))
        })
        readableStream.on('error', reject)
    })
}