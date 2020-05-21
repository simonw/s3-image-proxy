# s3-image-proxy

Tiny Starlette application for retrieving image files from a private S3 bucket, resizing them based on querystring parameters and serving them with cache headers so the resized images can be cached by a CDN.

Designed to work with Vercel.
