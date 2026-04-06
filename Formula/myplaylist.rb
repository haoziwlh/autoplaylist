class Myplaylist < Formula
  include Language::Python::Virtualenv

  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/py3/m/myplaylist/myplaylist-0.1.0-py3-none-any.whl",
      using: :nounzip
  sha256 "1c0867f4d80e5aa21667a235c3d04c2cfb32a031e11a58991a5d33a329ea6950"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = virtualenv_create(libexec, "python3.11")
    venv.pip_install "myplaylist==#{version}"
    bin.install_symlink libexec/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
