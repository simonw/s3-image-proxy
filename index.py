from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, RedirectResponse
from starlette.routing import Route
from PIL import Image, ExifTags
import httpx
import pyheif
import io
import os
import boto3


for ORIENTATION_TAG in ExifTags.TAGS.keys():
    if ExifTags.TAGS[ORIENTATION_TAG] == "Orientation":
        break


read_client = boto3.client(
    "s3",
    aws_access_key_id=os.environ["S3_AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["S3_AWS_SECRET_ACCESS_KEY"],
)

AWS_S3_BUCKET = os.environ["S3_BUCKET"]


def url_for_image(sha256, ext):
    key = "{}.{}".format(sha256, ext)
    return read_client.generate_presigned_url(
        "get_object", Params={"Bucket": AWS_S3_BUCKET, "Key": key,}, ExpiresIn=600,
    )


async def homepage(request):
    return JSONResponse({"error": "Nothing to see here"})


async def image(request):
    key = request.path_params["key"]
    sha256, ext = key.split(".")
    url = url_for_image(sha256, ext)

    # Fetch original
    async with httpx.AsyncClient(verify=False) as client:
        image_response = await client.get(url)
    if image_response.status_code != 200:
        return JSONResponse(
            {
                "error": "Status code not 200",
                "status_code": image_response.status_code,
                "body": repr(image_response.content),
            }
        )

    # Load it into Pillow
    if ext == "heic":
        heic = pyheif.read_heif(image_response.content)
        image = Image.frombytes(mode=heic.mode, size=heic.size, data=heic.data)
    else:
        image = Image.open(io.BytesIO(image_response.content))

    # Does EXIF tell us to rotate it?
    try:
        exif = dict(image._getexif().items())
        if exif[ORIENTATION_TAG] == 3:
            image = image.rotate(180, expand=True)
        elif exif[ORIENTATION_TAG] == 6:
            image = image.rotate(270, expand=True)
        elif exif[ORIENTATION_TAG] == 8:
            image = image.rotate(90, expand=True)
    except (AttributeError, KeyError, IndexError):
        pass

    # Resize based on ?w= and ?h=, if set
    width, height = image.size
    w = request.query_params.get("w")
    h = request.query_params.get("h")
    if w is not None or h is not None:
        if h is None:
            # Set h based on w
            w = int(w)
            h = int((float(height) / width) * w)
        elif w is None:
            h = int(h)
            # Set w based on h
            w = int((float(width) / height) * h)
        w = int(w)
        h = int(h)
        image.thumbnail((w, h))

    # ?bw= converts to black and white
    if request.query_params.get("bw"):
        image = image.convert("L")

    # ?q= sets the quality - defaults to 75
    quality = 75
    q = request.query_params.get("q")
    if q and q.isdigit() and 1 <= int(q) <= 100:
        quality = int(q)

    # Output as JPEG
    jpeg = io.BytesIO()
    image.save(jpeg, "JPEG", quality=quality)
    return Response(
        jpeg.getvalue(),
        media_type="image/jpeg",
        headers={"cache-control": "s-maxage={}, public".format(365 * 24 * 60 * 60)},
    )


def original(request):
    key = request.path_params["key"]
    sha256, ext = key.split(".")
    return RedirectResponse(url_for_image(sha256, ext), status_code=302)


app = Starlette(
    debug=True,
    routes=[
        Route("/", homepage),
        Route("/i/{key}", image),
        Route("/o/{key}", original),
    ],
)
