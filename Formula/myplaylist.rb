class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/d4/df/b899af3b0cef097d37c6d4bae391abd752ff78933f1d77a1db363693ffad/myplaylist-0.4.1-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "13c33882b9c0a2c09bfacc9eafa6de94ff67b78cf62c3ca5fbc95ce96352b76d"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
