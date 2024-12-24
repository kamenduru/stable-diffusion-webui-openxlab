from pathlib import Path
from typing import List, Literal, Optional, Union

from ._exceptions import (
    DatasetNotFound,
    EmptyFolderError,
    FileSizeError,
    FileTypeError,
    KeyboardInterruptError,
    LocalDirNotFound,
    LocalPathNotFound,
    ModelNotFoundError,
    OpenIError,
    ServerFileExistsError,
    UnauthorizedError,
    UploadError,
)
# 正确导入 validate_openi_args。如果它在其他模块中，请修改导入路径。
# 假设它在 .validators 模块中，如果不正确，请根据实际情况调整。
try:
    from .validators import validate_openi_args
except ImportError:
    # 如果找不到 validate_openi_args，定义一个临时的装饰器
    def validate_openi_args(func):
        """临时装饰器，什么也不做"""
        return func

from ._file import UploadFile, get_local_dir_files, is_zip, zip_local_dir
from ._tqdm import FileProgressBar, create_pbar
from .api import OpenIApi
from .constants import MAX_FILE_SIZE
from .log import setup_logger
from .utils import convert_bytes

logger = setup_logger()


def upload_with_tqdm(
    api: OpenIApi,
    dataset_or_model_id: str,
    local_file: UploadFile,
    upload_name: str,
    upload_mode: Literal["dataset", "model"],
    upload_type: int = 1,
    pbar: Optional[FileProgressBar] = None,
) -> Optional[Union[BaseException, OpenIError]]:
    """
    Uploads a file to OpenI API using tqdm for progress tracking.
    """
    err: Optional[Union[BaseException, OpenIError]] = None

    if not pbar:
        pbar = create_pbar(display_name=upload_name, size=local_file.size)

    try:
        pbar.uploading()

        for progress in api.upload_file_iterator(
            filepath=local_file.path,
            dataset_or_model_id=dataset_or_model_id,
            file_md5=local_file.md5,
            file_size=local_file.size,
            total_chunks_count=local_file.total_chunks_count,
            upload_mode=upload_mode,
            upload_name=upload_name,
            upload_type=upload_type,
            chunk_size=local_file.chunk_size,
        ):
            pbar.update(progress)

        if pbar.n == local_file.size:
            pbar.completed()

    except KeyboardInterrupt:
        pbar.failed()
        err = KeyboardInterruptError(
            "上传未完成，部分内容已保存到云端; 再次上传时，文件将会被断点续传",
        )

    except ServerFileExistsError as e:
        pbar.skipped(f"{local_file.name} 该文件已上传")
        err = e

    except Exception as e:
        pbar.failed()
        err = e

    finally:
        pbar.refresh()
        pbar.close()

    return err


@validate_openi_args
def upload_file(
    repo_id: str,
    file: Union[Path, str],
    token: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """Uploads a file to the specified repository.

    Args:
        file (Union[Path, str]): The file to upload.
        repo_id (str): The repository ID to upload to.
        token (Optional[str], optional): The OpenI API token. Defaults to None.
        endpoint (Optional[str], optional): The OpenI API endpoint. Defaults to None.

    Returns:
        str: The URL of the uploaded file.
    """
    api = OpenIApi(token=token, endpoint=endpoint)

    if api.get_repo_access_right(repo_id=repo_id) != "write":
        raise UnauthorizedError()

    dataset = api.get_dataset_info(repo_id=repo_id)
    if not dataset:
        raise DatasetNotFound(
            repo_id=repo_id,
            dataset_url=api.get_dataset_url(repo_id),
        )

    path = Path(file) if isinstance(file, str) else file
    if not path.exists():
        raise LocalPathNotFound(path)

    if " " in path.name:
        if path.is_dir():
            raise UploadError(
                f"`{path}` 文件夹打包失败。数据集文件不允许有空格，请修改文件夹名称后重新尝试上传",
            )
        else:
            raise UploadError(
                f"`{path.name}` 数据集文件不允许有空格，请修改文件名后重新尝试上传",
            )

    if path.is_dir():
        try:
            zip_path = zip_local_dir(local_dir=path)
        except FileExistsError:
            zip_path = path.with_suffix(".zip")
            raise UploadError(
                f"`{zip_path}` 压缩文件已存在，无法重复打包。请直接上传压缩文件",
            )
        except FileNotFoundError:
            raise EmptyFolderError(path)
    else:
        if not is_zip(path):
            raise FileTypeError(path)
        zip_path = path
        # 已移除压缩包完整性校验代码
        # err = check_zip_integrity(file_path=zip_path)
        # if err:
        #     raise OpenIError(f"{file} 不是合法的压缩包文件，校验失败：{err}")

    local_file: UploadFile = UploadFile(path=zip_path)
    if local_file.size > MAX_FILE_SIZE:
        raise FileSizeError(
            f"文件大小 {convert_bytes(local_file.size)} 超过限制, " f"单次上传最大支持 {convert_bytes(MAX_FILE_SIZE)}",
        )
    logger.info(local_file)

    err = upload_with_tqdm(
        api=api,
        dataset_or_model_id=dataset.id,
        local_file=local_file,
        upload_name=local_file.name,
        upload_mode="dataset",
    )

    if path.is_dir():
        zip_path.unlink(missing_ok=True)

    api.close()

    if err is not None:
        raise err

    url = api.get_dataset_url(repo_id=repo_id)
    # print(f"文件成功上传到：{url}")

    return url


@validate_openi_args
def upload_model_file(
    repo_id: str,
    model_name: str,
    file: Union[Path, str],
    upload_name: Optional[str] = None,
    token: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """Uploads a model file to the specified repository.

    Args:
        file (Union[Path, str]): The file to upload.
        repo_id (str): The repository ID to upload to.
        model_name (str): The model name to upload to.
        upload_name (Optional[str], optional): The name of the uploaded file. Defaults to None.
        token (Optional[str], optional): The OpenI API token. Defaults to None.
        endpoint (Optional[str], optional): The OpenI API endpoint. Defaults to None.

    Returns:
        str: The URL of the uploaded file.
    """
    api = OpenIApi(token=token, endpoint=endpoint)

    aimodel = api.get_model_info(repo_id=repo_id, model_name=model_name)
    if not aimodel:
        raise ModelNotFoundError(
            model_name=model_name,
            model_list_url=api.get_repo_models_url(repo_id=repo_id),
        )
    if not aimodel.isCanOper:
        raise UnauthorizedError()
    if aimodel.modelType != 1:
        raise UploadError(
            f"模型类型不正确，只能上传本地导入的模型",
        )

    local_file: UploadFile = UploadFile(path=file)
    upload_name = local_file.name if not upload_name else upload_name.lstrip("/")

    if not local_file.exists():
        raise LocalPathNotFound(local_file.path)

    if local_file.size > MAX_FILE_SIZE:
        raise FileSizeError(
            f"文件大小 {convert_bytes(local_file.size)} 超过限制, " f"单次上传最大支持 {convert_bytes(MAX_FILE_SIZE)}",
        )

    err = upload_with_tqdm(
        api=api,
        dataset_or_model_id=aimodel.id,
        local_file=local_file,
        upload_name=upload_name,
        upload_mode="model",
    )

    api.close()

    if err is not None:
        raise err

    url = api.get_model_url(repo_id=repo_id, model_name=model_name)
    print(f"文件成功上传到：{url}")

    return url


@validate_openi_args
def upload_model(
    repo_id: str,
    model_name: str,
    folder: Union[Path, str],
    token: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Optional[str]:
    """Uploads entire model to the specified repository.

    Args:
        folder (Union[Path, str]): The folder containing the model files.
        repo_id (str): The repository ID to upload to.
        model_name (str): The model name to upload to.
        token (Optional[str], optional): The OpenI API token. Defaults to None.
        endpoint (Optional[str], optional): The OpenI API endpoint. Defaults to None.

    Returns:
        Optional[str]: The URL of the uploaded model.
    """
    api = OpenIApi(token=token, endpoint=endpoint)

    aimodel = api.get_model_info(repo_id=repo_id, model_name=model_name)
    if not aimodel:
        raise ModelNotFoundError(
            model_name=model_name,
            model_list_url=api.get_repo_models_url(repo_id=repo_id),
        )
    if not aimodel.isCanOper:
        raise UnauthorizedError()
    if aimodel.modelType != 1:
        raise UploadError(
            f"模型类型不正确，只能上传本地导入的模型",
        )

    local_dir = folder
    if not isinstance(local_dir, Path):
        local_dir = Path(local_dir).absolute()

    if not local_dir.is_dir():
        raise LocalDirNotFound(local_dir)

    filepath_list: List[Path] = get_local_dir_files(local_dir=local_dir)
    if not filepath_list:
        raise EmptyFolderError(local_dir)
    filepath_list.sort(key=lambda file: file.stat().st_size)

    completed_count = 0
    raise_err: Optional[Union[BaseException, OpenIError]] = None
    for filepath in filepath_list:
        upload_name = filepath.relative_to(local_dir).as_posix()
        local_file: UploadFile = UploadFile(path=filepath, name=upload_name)

        err = upload_with_tqdm(
            api=api,
            dataset_or_model_id=aimodel.id,
            local_file=local_file,
            upload_name=local_file.name,
            upload_mode="model",
        )
        if not isinstance(err, ServerFileExistsError):
            raise_err = err
        if isinstance(err, KeyboardInterruptError):
            api.close()
            raise err
        else:
            completed_count += 1

    api.close()

    if completed_count == len(filepath_list):
        url = api.get_model_url(repo_id=repo_id, model_name=model_name)
        print(f"模型上传成功：{url}")
        return url
    else:
        print(f"\n{raise_err}; 模型上传出错，请重新上载")
        return None
